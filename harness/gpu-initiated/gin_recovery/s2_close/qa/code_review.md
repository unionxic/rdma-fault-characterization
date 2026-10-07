# Code review: gin-s2-close library change and get-mode driver

Independent review, 2026-10-07, read-only (no build, no cluster run). Tags: `[source]` read in code, `[measured]` checked
in the raw logs or `../results/20261007/trials_scored.csv`, `[inferred]` reasoning, `[unverified]` not checked.

## Scope and what was checked

- Library change: [`../s2r_layer.diff`](../s2r_layer.diff), applied in the session scratch tree
  `agent_ts2r/nccl-src` (git HEAD = step-2 final, working tree = this change). Line numbers below are in that tree,
  which equals pristine v2.32.3-1 + [`../gin_transparent_s2r.diff`](../gin_transparent_s2r.diff).
- `git diff HEAD -- src` of that tree has the same md5 as `s2r_layer.diff` (`48857d32`), and the scratch build
  outputs match the deployed files in [`../deploy_check.txt`](../deploy_check.txt): libnccl `ba4984bd`, get-mode
  driver `f3de7a38` `[measured]`. That the driver binary was built from the committed `../../gin_ts2.cu` (commit
  `b72dd102`) is `[unverified]` (not rebuilt; the source mtime precedes the build).
- Driver change: `git diff master -- harness/gpu-initiated/gin_recovery/gin_ts2.cu` (get mode only).

## Result

No bug found. No finding could have changed a measured result of this study; the evidence is given per finding.
Six risks and four nits follow, ranked.

| # | Severity | Where | One line |
|---|---|---|---|
| R1 | risk (medium) | `dev_runtime.cc:1647-1650` | user waits can now be released by paths other than `ncclCommAbort` on this comm |
| R2 | risk (medium) | `gin_gdaki.h:1072-1076`, `gin__funcs.h:101` | a released wait returns `ncclSuccess`; the user kernel cannot tell it from completion |
| R3 | risk (low) | `gin_host_gdaki.cc:3323-3330` | idle-close WARN also fires on ordinary teardown FIN; the socket-close columns count it |
| R4 | risk (low) | `gin_host_gdaki.cc:1973-1975` | flag gated on env only, not on transparent recovery actually being on |
| R5 | risk (low) | `gin_host_gdaki.cc:3296-3298` | mute attach/detach slip while the helper is inside a round |
| R6 | risk (low) | `gin_host_gdaki.cc:3264-3272` | "mute on" line printed even if no socket got the filter |
| N1-N4 | nit | various | logging scope, WARN level, stale comment, old devComm layout |

## Findings

### R1. Waits released without the user's `ncclCommAbort` (risk, medium)

`dev_runtime.cc:1647-1650` hands the user devComm `comm->abortFlagDev`. Before this change only
`setCommAbortFlags` in `ncclCommAbort` mattered to user kernels (they had a null flag). Other writers of the same word
`[source]`:

- `ncclCommRevoke`: sets 1 (`init.cc:3446`) and resets 0 at the end of the async job (`init.cc:3417`).
- `ncclCommShrink` with `NCCL_SHRINK_ABORT`: sets 1, synchronizes only NCCL's `deviceStream`, resets 0
  (`init.cc:3666-3670`).
- Group launch: if any async job of a multi-job group fails, every job's `abortFlagDev` is set to 1 and never reset
  (`group.cc:118-125`, `group.cc:655-662`).
- `splitShare`/`shrinkShare` children share the parent's word (`init.cc:3592`), so aborting one releases the other's
  user kernels.

Failure scenario: an application waits in `waitSignal` in a long-running kernel; after a peer failure it calls
`ncclCommShrink(..., NCCL_SHRINK_ABORT)`. For the length of the `deviceStream` sync the word is 1; a waiter that samples
it (every 10 000 polls, `utility.h:79-87`) returns `ncclSuccess` (`gin__funcs.h:101`) and the kernel consumes a slot
that never arrived. The word is 0 again afterwards, so the effect is racy and silent.

Effect on this study: none. The driver uses one communicator, no revoke, shrink or split; every NCCL call runs outside a
group (single-job path, `group.cc:77-82`, sets no flag) `[source]`. The prediction "nothing is released before the
abort" (RB1b) held 10/10 `[measured]`. Suggestion: give user devComms a separate pinned word written only by
`ncclCommAbort`, or document these paths as releasing user waits.

### R2. A released wait looks like a completed one (risk, medium)

On abort, GIN waits and flushes return `ncclSuccess` (`gin_gdaki.h:1072-1076` in the transparent-recovery poll,
`1163-1166`, `1257-1262`; `gin__funcs.h:101`). This is stock semantics, but NCCL's own kernels check the abort flag
themselves; a user kernel has no such signal. It also changes the step-1 teardown statement in `init.cc:3507-3510`
("a device thread held across a recovery then returns an error at once"): a thread polling in the transparent-recovery
poll now returns success at its next abort sample, before `ncclGinGdakiTsCommTeardown` poisons the gates (it joins the
helper, watcher and hook first). Threads parked in the gate do not read the abort flag and still fail on the poison.

Failure scenario: a sender loop of put + flush; the abort releases a flush with `ncclSuccess`, the loop posts the next
put on a still-open gate toward a peer that may have freed its memory; a persistent loop never exits, so the teardown's
`cudaFree` blocks as before.

Effect on this study: none. The driver reads `TxOut`, `RxOut` and `GetOut` only when the kernel finished before
`teardownExit` (`gin_ts2.cu:877-880`, `929`, teardown at `1025`); after the abort it records only the stream state
(`145-154`) `[source]`. In all 25 release-cell receiver traces the kernel had exited when the abort returned
(`post_abort_state=exited`) `[measured: results/20261007/rel/*_r1.kv]`.

### R3. Idle-close WARN fires on ordinary teardown (risk, low; scoring)

`gin_host_gdaki.cc:3323-3330` now logs at WARN every idle socket loss, including the FIN of a peer that simply tore down
first. `rows_extra.py` counts every such line (`n_sock_close_r0`) and takes the first line's cause.

- Rank 1 logged `cause=FIN` in every scored trial of the release, get, 1 s mute and new-library replication cells with
  recovery on (the killed-peer cell aside); rank 0 logged FIN in 7 of 10 scored new-library latency runs and in all 5
  peer-kill trials `[measured: trials_scored.csv]`.
- Failure scenario: the 1 s mute control (RD3) requires `n_sock_close_r0 == 0`. Had rank 1 torn down first, a teardown
  FIN would have failed the control although the mute closed nothing (a false failure, not a false pass).
- Effect on this study: none. Rank 0 had 0 close lines in all 5 trials of that control; in the 8 s mute cell and the
  mute + peer QP error cell, rank 0 had exactly one line, `ETIMEDOUT`, seconds before teardown (10/10 each)
  `[measured]`. `sock_close_cause_r1` is FIN in most cells for this reason and is not a fault signal.
- Suggestion: skip or demote the line when the local side is stopping, or score only lines before
  `abort_start_mono_ms`.

### R4. Flag gating ignores whether transparent recovery armed (risk, low)

`ncclGinTsUserAbortEnabled()` (`gin_host_gdaki.cc:1973-1975`) checks the three env params only. Transparent recovery
can still be off for a user devComm: `gdakiTsSetup` declines without `NCCL_GIN_FAULT_CLASSIFY=1`, with companion QPs, a
non-GPU doorbell or a non-ring CQ (`3361-3373`), gate setup can fail (`3622`), or the backend may not be GDAKI. The flag
and the WARN "user devComm abort flag set" then appear with recovery off. Non-transparent GDAKI waits then take the
abortable polling loop instead of the blocking poll (`gin_gdaki.h:1121-1137` against `1140-1167`, `1225-1263`) and error
reports name path "abortable" instead of "wait-blocking" or "flush-blocking". Functionally equivalent apart from
abortability.

Effect on this study: none. The settings check required `ts_on_r* >= 1` in addition to `ua_r* >= 1` (section 8), so
`ua` alone was never taken as evidence that recovery was on. The recovery-off control (RB5) uses
`NCCL_GIN_FAULT_TRANSPARENT=0`, where the gate does hold. No latency effect: the device path differs only in one flag
load per 10 000 polls and the path label, and the two abort-flag latency controls (RB6a, RB6b) had equal medians
`[measured: SCORE.md]`.

### R5. Mute schedule slips during a round (risk, low)

`gdakiTsTestMute` runs only at the top of the helper loop (`gin_host_gdaki.cc:3298`). While the helper is inside a round
(`gdakiTsInitiate` at `3339`, `gdakiTsRespond` at `3316`), attach and detach wait for the round to end, bounded by
`NCCL_GIN_TS_ROUND_MS` (25 s) and the handshake bounds. A mute that should end during a round lasts longer, one that
should start during a round starts late.

Effect on this study: none. In all three mute cells the start (300 or 500 ms) and the 1 s and 8 s ends fell in idle time
before the faults (3000, 6000, 12 000 ms); the 30 s end of the mute + peer QP error cell came after the process ended
`[measured: results/20261007/mute/*.log, 25 mute-on and 15 mute-off lines per rank]`.

### R6. "Mute on" printed even if attach failed everywhere (risk, low)

`gin_host_gdaki.cc:3264-3272` prints the "on" line with `peers=<n>` even when `n == 0`; failures go to a separate line.
The settings check `n_mute_on_r0 >= 1` does not require `peers=1`, so a silent attach failure would make the 1 s mute
control (RD3) pass vacuously (no socket closes either way).

Effect on this study: none. All 50 "on" lines have `peers=1` and no `SO_ATTACH_FILTER failed` or parse-failure line
exists in `results/` `[measured]`.

### Nits

- **N1** `gin_host_gdaki.cc:3046`, `2994-3004`, `3093-3110`, `3162`: `closeCause` is logged only on the idle path.
  In-round losses decline without it, and the RETRY_EXC decline says "the peer's socket shows FIN/RST" when the socket
  actually died of ETIMEDOUT (all 10 mute + peer QP error trials). Appending `pe.closeCause` to decline texts would make
  that result self-explanatory. `closeCause` is never cleared (harmless: every `-1` path rewrites it).
- **N2** `dev_runtime.cc:1649` and `3328`: WARN for routine events. WARN also overwrites the `ncclGetLastError` string
  (`debug.cc:291-295`), so a teardown FIN or the per-devComm abort-flag line can replace a real error message. The driver
  does not call `ncclGetLastError` `[source]`.
- **N3** `gin/gin_host.cc:21-26`, `370`: the null-`abortFlag` test now tells user from internal contexts only during the
  setup call. Any later host code using the same test would misclassify user devComms; an explicit `isInternal`
  argument would be safer.
- **N4** device code built against the 2.29.2 devComm layout has no `abortFlag` field (`devcomm/devcomm_v22902.cc`), so
  the WARN says "set" but nothing is released. The 2.29.7 and 2.30.0 layouts copy it (`devcomm_v22907.cc:117`,
  `devcomm_v23000.cc:146`). The study driver uses the current layout (no copy).

## Checked and correct

- **Ordering.** The assignment is after `NCCLCHECKGOTO(ncclGinDevCommSetup(...))` (`dev_runtime.cc:1643`) and inside
  the GIN branch. `ncclGinFaultUserCtx` is computed and cleared inside the setup (`gin_host.cc:370`, `390`, `419`), and
  contexts, the error hook and the recovery helper are created synchronously there, so they are built as user contexts.
  No host code reads `devComm->abortFlag` afterwards (only `ncclDevCommDump`). The compat copy (`1725-1727`) runs after
  the assignment.
- **All creation paths.** Both user paths call `ncclDevrCommCreateInternal(..., isInternal=false)`: the async job
  (`dev_runtime.cc:1795`) and the enqueue path (`group.cc:388`). Internal symmetric-kernel devComms
  (`sym_kernels.cc:254`) are unchanged.
- **Multiple communicators.** Each devComm gets its own comm's word; teardown is keyed by comm
  (`init.cc:3511`). Shared words only with split/shrink sharing (R1).
- **Memory.** `abortFlagDev` is mapped pinned memory freed in `commFree` (`init.cc:390`) after the device-memory frees,
  which wait for running kernels. `closeCause` writes are bounded by `snprintf` (24 B; longest name 12 characters). The
  BPF program on the stack is copied by the kernel at `setsockopt`.
- **Thread safety of the mute switch.** Attach and detach run on the helper thread, which is the only thread that sends or
  receives on these sockets while it runs (rounds run inside it). Sockets are closed only after the helper is joined
  (`gdakiTsStop`, `3727-3741`; teardown `3672-3676`), and `ts->peers` is not resized after setup. In the kernel, filter
  attach and detach are RCU swaps, safe against concurrent `recv`/`send` `[inferred]`.
- **Filter semantics.** A classic BPF program returning 0 makes `tcp_v4_rcv` discard the segment before TCP processing,
  so data, ACKs, FIN, RST and keepalive replies are all dropped on that socket only `[inferred, kernel source not checked
  here]`. Consistent with the measured `ETIMEDOUT` closes on both ranks in 20/20 long-mute trials and no close in the
  1 s mute.
- **Accidental enable.** Low. `NCCL_GIN_TS_TEST_SOCK_MUTE` is read only in `gdakiTsTestKnobs`, which runs only when
  transparent recovery armed. Empty is off; `0`, `500`, `-1:5`, `5:0` are rejected with a WARN. `sscanf` accepts
  trailing junk and `%d` overflow is undefined (nit). It is read with `getenv`, so it is not set by `nccl.conf`, but with
  `NCCL_DEBUG` unset neither the parse WARN nor the "TEST knobs" line prints, so an inherited variable would mute the
  helper silently. There is no master "test knobs allowed" switch, as for the earlier test knobs. `cells.sh` passes it
  per command (`EXTRA_ENV=... run`), so it cannot leak between cells `[source]`.

## Get-mode driver (`gin_ts2.cu`)

Correct for the cells that used it `[source]`:

- `gin.get(team, peer, sendWin, goff, recvWin, goff, n)` matches `gin.h:337` (remote window first): rank 0 reads rank
  1's send window into its own receive window.
- Rank 1 is not a sender in this mode, so its send window keeps the seed-7 get pattern (`736-741`). Rank 0's receive
  window is poisoned and no other transfer writes it (rank 0 is not a receiver).
- Bounds: `getBytes <= bytes` (`616`) and `winBytes = bytes * iters` here (P = K = 1, no reuse), so every get stays in
  the window.
- The check runs only after the flush returned `ncclSuccess`; the flush waits for the last ticket, which is the get, and
  ends with an acquire system fence; the loads are volatile. The pattern depends on iteration and byte, so a missing,
  poisoned or misplaced get is detected.
- `GetOut` is read only if the kernel finished (`909-914`), never after the abort.

False failure: would need READ data to become visible after its CQE; the CQE write is ordered after the data writes
`[inferred]`. Measured: 5 fault-free runs, 120/120 gets exact each `[measured]`.

False pass: none happened. Two ways it could:

- `gin_ts2.cu:616` does not reject mode `F2` or `GIN_TS_CONTINUE`. With `GIN_TS_GET=1` and mode `F2`, `txGetKernel`
  ignores `badIt`, so the remote access fault is silently not applied and the trial can look recovered. The cells use
  only F1 (local QP error) and no fault.
- The exclusion rule checks only `fault_after_launch_ms > 0`, not that the fault came before the last get. A fault after
  the loop would count as a trial with no decline. Measured: faults 564–1122 ms after launch, loops about 2160 ms,
  `tx_done` 32–63 of 120, all 10 declined with mask `0x6` `[measured]`.

Pre-existing, not part of this change: device wait bounds are SM cycles computed from `cudaDevAttrClockRate`
(`gin_ts2.cu:682-685`), so they end early when the SM runs above that clock. This fits the flag-off control's receiver
abort of 14 275–14 339 ms instead of the predicted 15 000 ms or more (RB3) `[measured value; cause inferred]`.
