# gin-peer: code review after the main run

Reviewer: an independent agent, 2026-10-09, after holds H1–H8 (`results/20261009/`, 203 trials and runs, scored 09:53).
Read-only review: no study program, runner, scorer or Python was run, nothing ran on the cluster, no git write, and the
repository's address filter was not run. Files were read directly; the tag was read with `git show prereg/gin-peer-v1:<path>`
(no filter); counts and times below come from `grep`/`awk` over the raw per-trial files.

Marks: `[source]` read in code; `[measured]` read by this reviewer from the raw per-trial files (`*_meta.txt`, `*_r*.kv`,
`*_r*.log`, `*_decoy.out`, `hold_*.out`), not copied from `SCORE.md`; `[inferred]`; `[unverified]`.

Paths: "tree" is `agent_ts2hq/nccl-src` in the session scratch. `gin_host_gdaki.cc` means
`src/transport/net_ib/gdaki/gin_host_gdaki.cc` and `gin_gdaki.h` means `src/include/nccl_device/gin/gdaki/gin_gdaki.h` in the
tree. Scripts without a folder are in this study folder; the two-rank driver is `../gin_ts2.cu`.

## Verdict

- **Measured results: nothing found that biased or invalidated them.** No blocker, no high finding. Everything that produced
  `SCORE.md` (scorer, parsers, cells, holds, runners, drivers, predictions) is identical to the tag, apart from one
  address line that the repository's filter rewrites (Focus 4). The main-run folder holds only H1–H8 files written after
  the tag. A spot recount of the key observables agrees with `SCORE.md` (last section).
- **The four changes are correct and safe for what they claim**, inside the measured scope:
  1. Port choice: the range lies below the ephemeral range, every candidate is checked on both nodes, and a rank sends
     nothing before it has a valid greeting.
  2. Per-peer abort words: a decline, death or overrun raises only that peer's word. Word 0 goes up only when every gated
     peer is down, or on abort, aborting shrink and revoke. No lock-order cycle, no torn pointer, and the free point is
     unchanged.
  3. Review fixes: (a) both ranks plan before their own commit, and the plan stays valid across the commit. (b) The
     watchdog charges each outermost phase once, to the round and peer that own it, and a check follows every phase
     before anything is published. (c) FAIL is sent only after the nonce check and is never taken as death. The three low
     fixes do what §9.1 (g) says.
  4. Cause-based hand-off: every uncertain path ends in the stock answer.
- **One medium finding is a design trade-off that the conclusions must carry** (M1). At three or more ranks, waits that
  name no peer are no longer released when one peer dies. The run measured them only with a device timeout.
- **Low findings:** a shrink-time race opened by the new "peer already released" checks (not seen in the run); §8 rules
  that the scorer does not encode (none applied in this run); a wrong sentence in §9.2 about where the control drivers
  differ; the port check-then-bind window and the coverage of the decoy test; the 3c result's dependence on a harness
  switch that keeps the declining rank alive; wording.

## What was checked

| Area | How | Result |
|---|---|---|
| Layer vs tree | `git diff` of the scratch tree against its hf commit; `md5sum` | equals `hq_layer.diff` (`34ab6201`); 5 files; installed device headers in `build/` and `build-hqp/` equal the source header (`0aba0415`) `[measured]` |
| Driver sources vs build | `md5sum` of `../gin_ts2.cu`, `gin_mr.cu` against `agent_ts2hq/out/build_info.txt` | equal (`92a78218`, `7b238951`); binaries `3e053ff2`, `7f0fc272` as in §5 `[measured]` |
| Deploy | `deploy_check.txt` | md5 equal on both nodes; existing bundle unchanged (46 files); `ldd` resolves each bundle's own libnccl, `mr/hq` with `hq` and `hf` `[measured]` |
| Post-tag changes | `git diff prereg/gin-peer-v1 HEAD`, `git status`, per-file md5 of tag vs working copy, mtimes | none (Focus 4) |
| Main-run folder | `find -newermt` against the tag time | 1453 files, all after 09:00:54; after 09:51:40 only the scorer outputs `[measured]` |
| Spot recount | raw logs and kv of the cells listed at the end | agrees with `SCORE.md` |

## Focus 1: the library layer

**1.1 Per-peer words and word 0.** `[source]`
- Every word write is under `gdakiUaMu`: `ncclGinTsUserAbortRaise` (`gin_host_gdaki.cc:2400–2422`) and `gdakiUaRaisePeer`
  (2427–2470). The peer word is stored before word 0, and the device treats both as "fail", so their order does not
  matter.
- After the "every peer" path has set `e->why`, a later abort returns early (2408) and skips the words still at 0. Those
  words belong to peers outside `expected`. No gate carries them, because `gdakiTsPosterWordStep` writes only gated peers
  (5240–5249). So nothing is missed.
- `expected` is filled in `ncclGinTsUserAbortWord` (2386–2395) from the helpers registered by then. The registry push
  (1613–1616) comes before `gdakiTsStart`, and `gated` is set in the synchronous setup (5640, 5662). So `expected` is
  complete when a devComm is created. A later devComm on the same communicator can only add peers. `[measured]` no
  survivor raised its devComm word in the rank-3 kill cell (0 lines in 10 trials).
- Lock order: `outMu` → `gdakiUaMu` → `gdakiRecRegMu` (decline, watchdog, `ncclGinTsUserAbortWord`), and `outMu` →
  `gdakiRecRegMu` (teardown, 6006–6011). No path takes them in the reverse order.

**1.2 Device-side ordering.** `[source]`
- The host stores into pinned memory with release. The device loads with a relaxed system-scope atomic
  (`utility.h abortIsError`). The word is monotonic and nothing else is read on the strength of it.
- The gate pointer is written as two 4-byte copies, high half first; each copy is waited for (`gdakiRecCopyWait`), and
  bit 0 is in the low half. So the device never acts on a half-written pointer (unchanged from gin-harden).
- Cadence: a parked thread checks every 64 polls (`gin_gdaki.h:258–262`). The poller checks right after `testAbort`
  resets its counter, i.e. every 10 000 polls (1116–1120). Both checks come after the completion test (1083–1088), so a
  WQE that completed is never failed. Posters skip a duplicate read, because their `dl.abortFlag` is the same word
  (`tsQpWordError`, 230–233).

**1.3 Lifetime.** `[source]`
- The array is freed in `commFree` after the device memory (`init.cc:403`), the same point as gin-harden.
- An orphaned helper writes into the communicator only through `gdakiTsToComm` (2712–2718).
  `gdakiUaPeerRaised` (2475–2480) only reads the registry, which is erased at free, so it returns false and dereferences
  nothing.
- More device paths now read the array than in gin-harden (L5).

**1.4 Plan before commit (3a).** `[source]`
- Responder order (4725–4807): firmware check, peek, GID, plan, Commit, check, baseline, check (new, 4758), ACK, DONE,
  Apply. A rejected plan sends NACK 15 and a plan not attempted sends NACK 16 (4740–4744).
- Initiator order (5091–5114): ACK, abandoned check, GID, plan (5100–5104), Commit, check, baseline, Apply (which checks
  again, 4225–4229), DONE.
- The plan reads `rq.snap`, `rq.epochWqes` (both set at Prepare), the send ring and the rescue area. Commit writes the
  device QP struct (built from `rq.snap`, 2090–2100), not the ring. The gate stays closed from quiesce, so no device
  thread writes the ring or the rescue area between plan and apply. So the plan is still valid after the commit.
- Every rejection path declines before the rejecting rank commits. A rejection by the initiator reaches the waiting
  responder as FAIL, and the responder declines without re-posting.
- Timing: the plan's ring copy now runs before the ACK, inside the initiator's ACK bound (handshake + quiesce + drain +
  path wait, 4992). `[measured]` In the responder-rejection cell rank 0 never logged a plan line, no rank logged a
  recovered line, and rank 0 declined with the NACK-15 reason (10/10). The control logged one recovered line (5/5).

**1.5 Watchdog bookkeeping under `fwMu`.** `[source]`
- The outermost guard opens and closes a phase under `fwMu` (1441–1464), and the watchdog decides under the same lock
  (3013–3027). So a charge always names the active phase's peer and round. `fwPhaseSeq` makes the charge happen once per
  phase.
- `fwRound` changes only between phases, on the helper thread (4916, 5164). The `ovRound == fwRound + 1` encoding means a
  charge made between rounds (after round j it stores j+1) never matches the next round (j+1 compares with j+2).
- Every firmware phase is followed by `gdakiTsFwCheck`, or by the peer-raised check in plan or Apply, before anything is
  published. This holds for both roles and for the tie-break yield path, which enters `gdakiTsRespondPrepared` at 4725.
- Clock marks (1358–1361) run outside `fwMu` but only on the phase's own thread, because `ncclGinRecover*` refuses to run
  when transparent recovery is active (2218–2223). `[measured]` in the four-rank overrun cell the charge named round 1 and
  peer 1; rank 2's later round with rank 0 recovered (10/10).

**1.6 FAIL replies and nonces.** `[source]`
- A HELLO's nonce is checked before the FAIL branch (3729–3739). A PROBE gets FAIL only with this context's nonce
  (3707–3711).
- Receivers accept FAIL only when it has the right type, `from == p` and the nonce (3522, 3620).
- `peerFailed` is not death: refusals are ignored (3317) and `cDeaths` is not counted. A pending decline runs in the
  helper loop (5462–5466), or at once in a fault waiting for the reconnect (4886–4889).

**1.7 Cause propagation.** `[source]`
- Only a peer's own `local`, carried in FAIL or NACK, becomes `peer-reported` (`gdakiTsRemoteCause`, 2589–2592).
  Everything else that comes from the peer, and an older peer with pad 0, is `unknown`.
- `ncclGinTsBlameQuery` returns −3 on any non-peer-side raise, and `commShrinkAbortReady` keeps the stock answer
  (`init.cc:3628–3633`). So misclassification can only make the shrink keep the stock answer, never let it through.
- `[measured]` shrink decisions in all logs: 15 "keeps ... (local)" (the two local-cause cells, `hq`), 20 "proceeds ...
  rank(s) 1" and 30 "proceeds ... rank(s) 3", exactly the cells' designs.

**1.8 The production macro.** `[source]` The layer adds no logic under `NCCL_GIN_TS_PRODUCTION`. It changes only log
levels (`GIN_TS_NOTE`, the dev_runtime and init.cc lines) and keeps the test switches out (`badRepost`, 4121–4130). The new
per-peer release line and the "every peer" line are WARN in both builds, as the §3.1 table says.

**1.9 Can a healthy peer's wait fail, or a failed peer's wait succeed?**
- A healthy peer's wait can fail only through word 0 (every peer down, abort, shrink, revoke) or through the per-context
  sticky flag of a blocking `wait()`/`flush()` (pre-run review M3; `tsPoison`/`tsFail` set it,
  `gin_gdaki.h:173–180, 1032–1038`). The per-peer timed wait and the per-edge contexts of `gin_mr` avoid the sticky flag
  (see M1).
- A failed peer's wait can succeed only when nothing was outstanding (`sq_rsvd_index == 0`, 1156), when the WQE completed
  before the error, or when the gate write was blocked before the word reached the gate (pre-run L4). No new path found.

**1.10 Pre-run review fixes re-checked in code.** `[source]`
- M1 (cause in FAIL/NACK): 2585–2600, 4469–4470.
- M2 (one charge per phase): 3019–3022.
- L2 (NACK 16): 4075–4087, 5159–5162.
- The four nits: `ovPeer` is gone, the responder's NACK has the nonce (4714, 5154), and the REQ-time word check exists
  (5159).
- Still open as documented: pre-run M3, M4, L1, L3–L8.

## Focus 2: drivers and runners

**2.1 Port choice and the check-then-bind window.** `[source]`
- `pick_port` (`portpick.sh:30–45`) checks each candidate with `ss` on rain and over ssh on sunny, for any state including
  TIME_WAIT. An ssh failure counts as busy.
- The window between the check and rank 0's `bind` (`../gin_ts2.cu:897`, `gin_mr.cu:693`) spans the GID probe and the
  remote launch, about a second. In that window only an explicit bind by another process into 29000–30999 can take the
  port (L3).
- `[measured]` 195 of 203 trials took their first candidate. The 8 that skipped one or more are exactly the 8 port-cell
  trials with the occupier. Trial `pq_rdv_b_n5` also skipped 29355 and 29356 (meta `port_skipped=29354,29355,29356`),
  the rendezvous and decoy ports of `pq_rdv_b_n1`, whose meta file was written 26 s earlier. They were most likely still in
  TIME_WAIT `[inferred]`. That is the intended conservative behaviour.

**2.2 Decoy and occupier.** `[source]`
- Both bind `0.0.0.0` on rain and run under `timeout -s KILL 120` and `150` (`portpick.sh:51–103`).
- They are stopped through the recorded `timeout` PID and its children found by `pgrep -P` (107–115), from the EXIT trap
  and after the trial. The decoy writes its counts on TERM.
- `[measured]` `decoy.out` exists in all 8 port-cell trials: `decoy_bytes=0`; connections 1 (two ranks) and 3 (four
  ranks).

**2.3 Rendezvous verification.** `[source]`
- Rank r > 0 reads and checks the 16-byte greeting before sending anything (`../gin_ts2.cu:938–958`,
  `gin_mr.cu:743–763`). Rank 0 accepts only a correct answer: rank 1 in `../gin_ts2.cu:900–920`, or a rank it still waits
  for in `gin_mr.cu:696–721`.
- Each foreign connection costs at most 2 s, rank r retries for at most 600 × 200 ms, and the runner's `timeout` bounds
  everything.
- Rank 0 sends its greeting, including the nonce, to anyone who connects. This is harmless: the nonce only separates
  trials.

**2.4 The child-devComm path.** `[source]` `childPhase` (`gin_mr.cu:389–576`):
- It is bounded by a watchdog thread (`GIN_MR_PHASE_S`, `_exit(8)`, 396–407).
- It reads every receive edge's signal base before an allreduce barrier, uses per-edge contexts and the per-peer timed
  flush, checks data and the exact final signal, and destroys the child.
- `[measured]` In one trial of the rank-3 kill-and-shrink cell, all three ranks have `ch_outcome=ok`, 3 ranks, 6 GIN
  contexts, `ch_tx_ok=2`, `ch_rx_ok=2`, and the child's own transparent-recovery lines (12 gated QPs).

**2.5 Kill by recorded PID.** `[source]`
- Two ranks: the child of the recorded remote `timeout`, only while that PID's command line still has the trial tag
  (`run_trial_hq.sh:99–107, 142–143`). Rank 0's kill uses the recorded local `timeout` PID (116–127).
- Four ranks: a PID recorded through parent links and re-checked through `/proc/<pid>/stat` (comm and ppid) right before
  the signal (`run_mr_hq.sh:100–124`).
- Nothing is killed by name. `[measured]` rank exit codes: 137 ×5 (the rank-0 kill cell), 255 ×15 (two-rank kills) and
  ×30 (rank-3 kills), 8 ×10 (ranks 2 and 3 of the local-cause shrink cell, `hq`), 4 for device errors, 0 otherwise.

**2.6 Bounded times.** Each rank is bounded by `timeout -s KILL (WATCHDOG_S + 20)`, each hold by `timeout -s KILL 880`
(`chain.sh:21`), the lock wait by 10 800 s, and the stale-process wait by 150 s. The ssh calls have no ConnectTimeout (L8).

**2.7 `GIN_TS_END_WAIT_S=12`.** `[source]` The driver sleeps before its teardown (`../gin_ts2.cu:1642–1643`) while the
helper keeps running, so the declined responder is alive to answer the re-dial or probe. `[measured]`
- In all 25 ACK-race trials (15 `hq`, 10 `hf`) the responder tore down 12.04–12.08 s after its own decline. Teardown took
  1–2 ms.
- H3 ran 9 min 49 s, inside its 880 s bound.
- `wall_s` in the meta file is rank 0's lifetime. It therefore excludes the linger in the cell started by rank 0 (rank 1
  lingers) and includes it in the cell started by rank 1 (rank 0 lingers). Do not compare `wall_s` across the two cells.
- The linger affects only the responder, and it is the same in both builds. Its effect on what 3c shows is L4.

## Focus 3: parser and scorer

- **Columns vs §3.1.** Each regex in `rows_pq.py:74–96` matches the format string in the tree.
  - Release lines: 2464, 2467, 2419/2421. The per-peer line does not match the devComm-word regex, and the
    `continue` (119) keeps it out.
  - Cause: 4475, 3044. Answer/received FAIL: 3452, 3435. Plan: 4205, 4198. Watchdog: 3030–3033. Cancel: 4660. Decline:
    4473. Keep/proceed: `init.cc:3651, 3664`.
  - `rows_hd.py`'s `uarel_why` reads only the devComm-word line, so B1's `fw-watchdog` means word 0 was raised.
  - `n_cancel_ack` counts only the initiator's cancel line. The responder's line reads "from rank", not "with rank".
- **Exclusions vs §8.** The order and content of `status2`/`status4` (`score.py:128–224`) match §8, with gaps in L2. No
  trial was excluded, labelled `config_*` or surplus, and no fill hold ran (`chain.out`: H1–H8 only).
- **Vacuous passes.** None found. Every prediction that tests for an absence also needs a present line or kv.
  - The test that no rank raised its devComm word is paired with exact per-peer and decline lists (B3, K2).
  - "No plan on rank 0" is paired with "rank 1 rejected" (A1).
  - Q2/Q3 need a decoy file and kv; a missing file gives `""`, which fails.
  - Q1 counts only the string "bind: Address already in use" in rank 0's log. That string is how both drivers report it
    (`perror("bind")`).

## Focus 4: changes after the tag

None.
- `git diff prereg/gin-peer-v1 HEAD` is empty. The tag points at HEAD `551c796f`. `git status` shows only the untracked
  `results/` (and now `qa/`).
- md5 of tag vs working copy is equal for `score.py`, `rows_pq.py`, `predictions.csv`, `cells.sh`, `portpick.sh`,
  `gin_mr.cu`, `../gin_ts2.cu`, and the imported `../scripts/ts2/rows.py`, `../s2_close/score.py`, `../harden/rows_hd.py`,
  `../handoff/rows_hf.py`, `../multirank/rows_mr.py`.
- `hold.sh`, `run_trial_hq.sh`, `run_mr_hq.sh` and `deploy_hq.sh` differ from `git show` in exactly one line each (17, 32,
  30, 16: the default ssh target). That is the repository's address filter; `git status` is clean. Compared by line number
  only, without printing the lines.
- Every scorer input has an mtime before the tag (latest 08:52:53). `predictions.csv` sha256 equals `PREREG.txt`.

## Findings

### Blocker

None.

### High

None.

### Medium

**M1. Waits that name no peer lose their prompt release on one death at three or more ranks; the run measured only the
timed form.** (design trade-off, pre-run review M4; must go into §17 and §18, not a bias)
- Where: `gdakiUaRaisePeer` raises word 0 only when every gated peer is down (`gin_host_gdaki.cc:2445–2457`). `waitSignal`,
  `waitCounter`, the barriers and the void forms read only word 0 (`gin__funcs.h`, e.g. 1386–1415).
- Failure scenario: four ranks, rank 3 dies, and a survivor's kernel waits with an untimed `waitSignal` for a signal that
  rank 3 was to send. In `hf` the decline raised the communicator word and the wait ended at once with an error. In `hq`
  the wait spins until the application aborts or shrinks. A host thread blocked in a stream synchronize cannot do that;
  only another thread that reads the async error can. For the unmodified applications this project targets, this is a
  liveness regression at three or more ranks. Two ranks are unchanged: the first decline is every peer.
- Effect on the measured results: none. `gin_mr` uses the timed `waitSignal` (`gin_mr.cu:321–322`, 10 s), and the cell
  predicted and measured exactly that: receives from the dead rank end by their own timeout (K3, K5, 10/10 and 5/5).
- Effect on conclusions: the survivor result (K1, 10/10) shows that per-peer posting and flushing keep working. It does not
  show that a survivor's application finishes, unless every peer-agnostic wait has a device timeout. Also, the per-edge
  contexts and the per-peer timed wait of `gin_mr` keep the per-context sticky flag out of the way (pre-run M3). A
  blocking `wait()`/`flush()` in a context shared with the dead peer would still fail, and the context-wide flush cell
  shows this for senders (6/6 failed).

### Low

**L1. An aborting shrink raises every parent word before its readiness check. The new "peer already released" checks can
turn a round that arrives in that window into a local-cause decline, which then makes the same shrink keep the stock
answer.**
- Where: `init.cc:3796` (raise all), then `ncclCommEnsureReady`/`commShrinkAbortReady` (3591, 3627). New checks:
  `gdakiTsRespond` NACK 16 (`gin_host_gdaki.cc:5159–5162`), plan code 16 (4084–4087), Apply (4226–4229).
- Failure scenario: survivor A calls the aborting shrink. Survivor B, still in its main phase, has a local QP error on its
  QP to A and sends a REQ in the milliseconds before A's readiness check. A answers NACK 16 and declines B with cause
  `local`. A's blame record now names a non-excluded peer, so A's shrink returns the stock error. In `hf` the round would
  have recovered and the shrink would pass.
- Effect: none on this run. `[measured]` no "already released" decline appears in any log, and all 30 survivor shrinks of
  the kill-and-shrink cell proceeded. The window is the device-stream synchronize, so the risk is small `[inferred]`.
  Possible fix: take the readiness snapshot before raising, or keep the per-peer check off for the shrink's own raise.

**L2. The scorer does not encode four §8 rules.** None of them applied in this run.
- Where:
  - `score.py:164–193` labels a failed configuration check `config_*` but does not stop the block.
  - The ">50 % refills → 자료 부족" rule is not implemented.
  - `status4` (197–224) has no test-switch-line check.
  - The copy condition of the four-rank local-cause cell uses `n_copy_to` summed over all ranks (206), not the stalled
    rank's.
- Effect: none. No trial was excluded or labelled, and no refill ran. `[measured]` by hand:
  - `fw_delay=4000@commit` appears only in rank 0's log in all 15 four-rank overrun trials.
  - `copy_stall=4000` appears only in rank 0's log in all 10 four-rank local-cause trials, and rank 0 logged the copy
    timeout in each of the 5 `hq` trials.
- Encode these before the scorer is reused.

**L3. The rendezvous port is checked, then bound, with nothing held in between, and a failed local `ss` reads as "free".**
- Where: `portpick.sh:21–45` → `../gin_ts2.cu:897`, `gin_mr.cu:693`; `portpick.sh:23`.
- Failure scenario: another process binds the chosen port explicitly inside the window of about 1 s (the kernel does not
  hand out 29000–30999 on its own).
- Effect: none seen (`[measured]` no bind failure in 203).
- Strength of Q1: at the earlier rate (7 of 500), 0 of 203 has a probability of about 0.06 even with no fix. The 0/203
  supports the claim; the out-of-range mechanism carries it.
- A bind retry inside the driver, or handing a pre-bound socket to rank 0, would close the window.

**L4. The 3c measurement depends on a harness switch that keeps the declining rank alive.**
- Where: `cells.sh:82–87` (`GIN_TS_END_WAIT_S=12` on the responder), added after pilot P0 and re-piloted before the tag.
- Without it (P0) the responder exited 0.34–0.38 s after its decline, the initiator's re-dial or probe was refused, and the
  initiator judged the peer dead about 1.25 s after the mute ended. The FAIL path never ran.
- With it, the FAIL path ran in all 15 `hq` trials. Rank 0 declined 234–437 ms after the mute ended in the re-dial form
  (n=10); rank 1 declined 227–276 ms after it in the probe form (n=5). The `hf` controls declined 8254–8458 ms and
  8231–8285 ms after it (n=5 each) `[measured]`.
- Effect: no bias, because both builds had the same condition. But the result holds when the declined rank stays alive,
  which is the case the fix targets: a rank that keeps serving other peers. Say so.
- Also, the FAIL carries the responder's cause `unknown` (its decline was "peer closed the socket before DONE"). So after
  this race neither rank's aborting shrink can hand off (`[measured]` rank 0 `cause=unknown` in the re-dial trials). That
  is conservative and should be stated next to item 4.

**L5. More device paths now read the pinned word array.**
- Where: `gin_gdaki.h:258–262, 1116–1120`. Before, only parked posters read the gate word. Now every parked waiter, and
  every 10 000th poll on every gated QP, reads it.
- Failure scenario: a kernel still running at `commFree` (misuse) reads freed pinned memory on more paths than in
  gin-harden. The free point is unchanged (`init.cc:403`).
- Effect: none. `[measured]` no STOP_cuda in the 8 holds, and no exit code 139.

**L6. §9.2 says the two-rank controls differ "only in the rendezvous before NCCL init, so only the library differs". That is
wrong.**
- `gin_gdaki.h` is header-only device code compiled into the driver. `build_hq.sh drivers` compiles against `build/include`,
  whose header carries `tsQpWordError` (3 uses). So the per-peer reads of parked waiters and pollers live in the `hq` driver
  (`3e053ff2`). The `hf`/`hfp` driver (`9493584d`) carries the `hf` header.
- Effect: none on verdicts. The two-rank controls are the correct previous stack, and the latency predictions (P1, P2)
  include the device change, as they should. But conclusions must attribute differences to "library + the driver's device
  code", not "library only".
- The four-rank controls (`mr/hq` with `hf` libnccl) do behave as `hf`. Every device entry point passes
  `comm.abortFlag` (`gin__funcs.h:984–1220`), the `hf` library puts that same word in the gate, and `tsQpWordError` skips
  a word equal to the caller's.

**L7. The decoy test covers a wrong magic only, and `rdv_decoy=rejected` is also written on a timeout.**
- Where: `portpick.sh:82` (greeting `NOTGINRDV0000000`); `rdvCheckGreeting` returns false on a short read
  (`../gin_ts2.cu:310–315`, `gin_mr.cu:223–228`).
- What is not tested: the realistic collision, a stale rank 0 of an earlier trial with the right magic and another nonce.
  The comparison is one expression (`memcmp(magic) && nonce ==`), so the risk is small.
- Effect: Q2/Q3 show "sent nothing to a foreign listener" (decoy bytes 0 in 8 of 8). They do not separately show "the
  nonce check rejects".

**L8. Unbounded ssh.**
- Where: `portpick.sh:24`, `run_trial_hq.sh:72, 102, 135–146`, `run_mr_hq.sh:69, 105, 116, 133–139`.
- Failure scenario: a hung ssh is cut only by the hold's 880 s KILL. A SIGKILLed runner skips its EXIT trap, so the
  occupier and decoy live until their own `timeout` (120 or 150 s).
- Effect: none seen. An ssh failure in `port_busy` counts as busy, which is safe. Add `-o ConnectTimeout=5 -o
  ServerAliveInterval=5`.

**L9. Comment and doc mismatches.**
- §9.1 (e) says every NACK now carries the nonce. The NACK 1 (tie-break off) and NACK 12 (pair check in the yielding
  initiator) built in `gdakiTsInitiate` (`gin_host_gdaki.cc:5033–5039, 5073–5079`) carry none. No effect: installed
  sockets do not check nonces.
- `gdakiTsEscalated`'s comment (4596–4598) says a rerun is "checked against a cap that is already reached". The code
  returns before the window check (4605), so a rerun is stopped only when `escalated` is already set (4601). That is the
  intended behaviour; fix the wording.

### Nits

- N1. The production configuration check (`score.py:175–177`) cannot tell `hqp` from `hfp`: neither has WARN start lines.
  Add the bundle path in the meta file and the driver kv `rdv` (`verified` only with the new driver) to the check.
  `[measured]` all 15 `hqp` trials have bundle `hqp` and `rdv=verified`; all 10 `hfp` trials have bundle `hfp` and no `rdv`
  key.
- N2. The four-rank runner counts leftovers by name on both nodes (`run_mr_hq.sh:139`). The two-rank runner counts by trial
  tag. Another study's `gin_mr` would count. The count is read-only, and `LEFT_STREAK` ended at 0.
- N3. `gin_mr.cu:403` writes `ch_outcome=timeout` from the watchdog thread. `kv()` writes the line and its newline in two
  stdio calls (95–103), so a concurrent `kv()` from the main thread could split the line. The main thread is blocked in the
  shrink or child when this fires, so it is unlikely.
- N4. The decoy and occupier listen on all interfaces. Binding to rain's management address would do.
- N5. The low fixes are unexercised. `[measured]` no "refusal ... forgotten" line and no escalation line in any main-run
  log. Their status stays `[미확인: 측정]` (§4).
- N6. The four-rank overrun is a sleep inside the guarded commit phase (test switch), not a slow firmware command. A
  command that never returns falls back to the 25 s round surface (§9.1 (d)), which was not measured.

## Spot recount by this reviewer (not the §10 independent recount)

All numbers were read from raw logs, kv and meta files with `grep`/`awk` `[measured]`.

| What | Cell@build (n) | Result | `SCORE.md` |
|---|---|---|---|
| Rank 1 rejects its plan before its commit: rank 0 has no plan line, rank 1 one rejection, no recovered line, rank 0 declines with the NACK-15 reason (A1) | `pq_repost_r1_b@hq` (10) | 10/10 | 10/10 |
| Control: rank 0 recovered once, then declined on rank 1's FAIL (A2) | `pq_repost_r1_b@hf` (5) | 5/5 | 5/5 |
| Rank 3 killed, per-peer flush: three per-peer release lines for rank 3, no devComm-word line, survivor edges with both rc "no error" 6/6 (K1, K2) | `mr4_kill3_peer@hq` (10) | 10/10 | 10/10 |
| Control: three devComm-word lines, survivor edges ok 0/6 (K4) | `mr4_kill3_peer@hf` (5) | 5/5 | 5/5 |
| Overrun charged to round 1 and peer 1; rank 2's round with rank 0 recovered; only the words 0-1 and 1-0 (one trial read in full) (B2, B3) | `pq4_fwslow@hq` (1 of 10) | as predicted | 10/10 |
| Decline after mute end: re-dial form / probe form / their controls (C1–C4) | `pq_ackrace_*` (10, 5, 5, 5) | 234–437, 227–276, 8254–8458, 8231–8285 ms | all pass |
| Responder stays after its decline | ACK-race cells, both builds (25) | 12.04–12.08 s | (config check) |
| Occupied candidate skipped, decoy got 0 bytes, all ranks verified (Q2, Q3) | `pq_rdv_b@hq` (5), `pq4_rdv@hq` (3) | 8/8 | 5/5, 3/3 |
| Shrink keeps vs proceeds lines | all cells | 15 keep (local), 50 proceed | consistent |
| Watchdog lines outside the two overrun cells | all cells | 0 | 0 exclusions |
| Hold safety | 8 holds | no STOP file; `gin-` iptables rules 0 before and after; rain cmd_err 2 and sunny 0 throughout; rain firmware-command failure sum 31 throughout; one new sunny mlx5 line in H1 ("FWTracer: Events were lost", not a command error) | |
