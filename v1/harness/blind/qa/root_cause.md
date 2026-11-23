# Root cause of four unexpected blind-apps results

Read-only analysis, 2026-10-09. No program was run, no cluster command was issued. Every number below was recomputed from the
raw files in `results/20261009/raw/<trial id>/` (`r0.log`, `r1.log`, `a0.log`, `a1.log`, `trial.meta`, the last one holds the
opened seal's true fault) and from `results/20261009/trials_scored.csv`. Nothing was copied from `SCORE.md` except the list
of trials to look at, which was checked against the raw files.

Markers: `[measured]` read from raw files, `[source]` read in code, `[inferred]` reasoning from the two, `[unverified]` not
checked. Times are seconds after the trial's anchor line (rank 0's `[nvshmem-t1] PE0 ... enabled:` line for NVSHMEM, the
`=== Comparing GIN ...` line for GIN), on rain's monotonic clock as the runner received the line. Rank 1 lines and agent
acknowledgements travel through ssh, so differences below 1 ms are not meaningful.

`<scratch>` is the session scratchpad `/tmp/claude-1009/-home-unionxic-rdma-error/17110666-879d-434a-a9a9-301ede25b7df/scratchpad`.
Sources read:
- NVSHMEM example: `<scratch>/agent_t1_380/src/examples/ring-reduce.cu` (the blind build compiled it unchanged, EXPERIMENT.md 5).
- NVSHMEM transparent-recovery tree (t1_380): `<scratch>/agent_t1_380/src/src/...`, diff
  `harness/gpu-initiated/nvshmem_ft/t1_380/nvshmem_ibgda_t1_380.diff` in the main checkout.
- GIN example: `<scratch>/agent_nb/nccl-232/docs/examples/09_gin_optimizations/01_ring_exchange/c/{kernels.cuh,main.cu}`.
- GIN `hq` tree: `<scratch>/agent_ts2hq/nccl-src/src/...`.
- DDP library: `harness/nccl-integration/stage2/{DESIGN_stage2.md,net_ib_stage2.diff}` in the main checkout.

## Summary

| Result | Root cause | Where the defect is | Fix |
|---|---|---|---|
| NVSHMEM ring-reduce, SIGSTOP of one PE: 2/7 silent wrong (`nvs:stop`, prediction N5, X1) | A data race in the example: after a size's last iteration, PE 0 validates and launches the next size, whose first kernel writes PE 0's input into PE 1's result buffer. Nothing makes PE 0 wait until PE 1 has copied that buffer to the host. A stall of PE 1's host across a size boundary lets the write land first | Example. A correct NVSHMEM produces the same result | A barrier after validation in the example. Nothing in the library |
| GIN ring exchange, QP fault: 14/16 hung (`gin:qperr`, G2) | Pilot hypothesis confirmed. The only code that reads the CQ is `flush`, which the kernel calls only after `waitSignal` returns. After the fault the signals stop, so both ranks spin in `waitSignal`, which reads only the signal word and the abort word. No error CQE is read, so no recovery starts. The 2 recovered trials are the two latest fault times (114, 115 ms), where one rank was already inside `flush` | Library (detection depends on the application polling) | Host-side detection: a periodic QP-state query or CQ peek by the existing watcher thread, which pushes a fault record so the helper runs the round |
| NVSHMEM ring-reduce, SIGKILL of one PE: 7/7 no error within 3 s, hung (`nvs:kill`, N4) | The library's own socket is created and sees the FIN within 0.5 ms in 7/7. But the helper only logs a FIN. A death verdict is issued only while handling a device fault record, which needs an error CQE. The survivor spins in `nvshmem_signal_wait_until` or the barrier's wait, with nothing in flight and nothing polling. Even a verdict would not end those spins | Library (no host-side death verdict, and no abort path into stock wait loops) | Decline on an unannounced FIN, and make the decline reach waits: an abort check in the wait loops, or a fail-stop exit |
| DDP, silent receive-QP fault: 6/6 recovered where a hang was predicted (`ddp:srq`, D4) | Multi-request recovery's sender-led path. When the hook fired, the receiver had already sent 1–3 more CTS. The sender posted those writes into the dead QP, got `RETRY_EXC_ERR` 3.57–3.76 s later on its own CQ (which NCCL's CPU proxy always polls), led a recovery in 1.94–2.13 ms and replayed 1–3 sends | Prediction basis: the 256 KiB all-reduce runs it came from left the sender idle | None needed. A hang stays possible when no authorized send is in flight (pilot P3 `srq-top`) |

Common thread `[inferred]`: in the CPU-proxy NCCL path the library owns the progress loop, so every error CQE is read. In the
two GPU-initiated libraries the CQ is read only inside operations the application calls (`flush`, `quiet`). Signal waits and
barrier waits are pure memory spins. A fault or a death that comes while both sides wait is invisible until something on the
host looks.

## 1. NVSHMEM `ring-reduce` under SIGSTOP: silent wrong in 37bd4c3d and 800579c9

### Evidence

**Which PE was stopped.** The opened seal gives target rank 1 (sunny) for both: `raw/37bd4c3d/trial.meta` `"target": 1`.
The SIGSTOP and SIGCONT went to PE 1's process: `raw/37bd4c3d/a1.log:3-4` (`AGENT sig=STOP pid=2631375 rc=0`,
`AGENT sig=CONT pid=2631375 rc=0`), `raw/800579c9/a1.log:3-4` `[measured]`. The evaluator's account (rank 0 paused, rank 1
went ahead) is reversed. Rank 1 was paused and rank 0 went ahead. In `trials_scored.csv` both trials have `j_target` 0 against
`target` 1 `[measured]`. The long silence on rank 0 (`max_gap0` 12.16 s and 9.08 s) is rank 0 waiting for rank 1 after it
resumed, see the mechanism below.

**The wrong data** `[measured]`. Only PE 1 printed validation lines. PE 0 printed none in either trial: no `error, data` line
in `r0.log` and no `suppressed` line in `a0.log`.
- `raw/37bd4c3d/r1.log:89-288`: the 200 lines the agent kept are `PE 1 error, data[i] = i expected data[i] = 2i` for
  i = 1–200 (first line `data[1] = 1 expected data[1] = 2`, last `data[200] = 200 expected data[200] = 400`).
- `raw/37bd4c3d/a1.log:5`: `AGENT suppressed name=validation count=8388407`. In total 200 + 8 388 407 = 8 388 607 = 2^23 − 1
  mismatches. That is every index of a 32 MiB `int` buffer except index 0, which cannot mismatch because 0 × 2 = 0.
- 800579c9 is identical: `r1.log:89-288` holds the same values and `a1.log:5` gives the same count, 8 388 407.
- So the 32 MiB pass on PE 1 was wrong at every nonzero index. The 16 MiB and 64 MiB passes were clean: the count leaves no
  room for other mismatches, and the first error line comes after the 16 MiB pass `[inferred from the count]`. Values are
  logged only for i = 1–200. They equal PE 0's contribution, `data_h[i] = i` (`ring-reduce.cu:215-217`), not the sum 2i.

**No library activity** `[measured]`. Neither PE has a recovery, decline, fault, timeout or watchdog line. Both end with
`teardown: rounds recovered 0, declined 0`: `37bd4c3d/r0.log:122`, `r1.log:292`, `800579c9/r0.log:122`, `r1.log:292`. PE 1's
`peer 0 library socket closed (FIN)` (`r1.log:291`) is the normal end-of-run FIN, which every fault-free run also shows.
Both exit codes are 0.

**Timeline of the seven valid stop trials** `[measured, recomputed from trial.meta, a*.log and PE 0's size lines]`. The
16/32/64 MiB columns give when PE 0 printed each size's timing line, which is just after that size's 150 timed iterations
complete on both GPUs. The excluded trial dcd30cbc (process ended before the fault) is not counted.

| trial | stopped PE | STOP | stopped for (s) | CONT | PE 0 16 MiB | PE 0 32 MiB | PE 0 64 MiB | result |
|---|---|--:|--:|--:|--:|--:|--:|---|
| 37bd4c3d | 1 | 1.322 | 5.145 | 6.467 | 0.799 | **2.243** | 14.407 | wrong (PE 1, 32 MiB) |
| 800579c9 | 1 | 1.086 | 2.757 | 3.843 | 0.538 | **1.431** | 10.509 | wrong (PE 1, 32 MiB) |
| a4be5433 | 1 | 2.391 | 4.053 | 6.444 | 0.556 | 1.442 | **3.197** | correct |
| e392a0dd | 1 | 2.432 | 5.644 | 8.076 | 0.537 | 1.430 | **3.201** | correct |
| ac3281ef | 0 | 2.258 | 5.639 | 7.897 | 0.803 | 2.253 | 10.807 | correct |
| c2b466da | 0 | 2.442 | 3.400 | 5.842 | 0.830 | 2.274 | 5.843 | correct |
| e89250ce | 0 | 1.390 | 4.547 | 5.937 | 0.537 | 5.938 | 7.716 | correct |

Two facts in this table:
- **PE 1's GPU kept running while its host was stopped.** In 37bd4c3d, PE 0 printed the 32 MiB line at 2.243 s, inside PE 1's
  stop (1.322–6.467 s), with a normal 9.51 ms per iteration. In a4be5433 and e392a0dd, PE 0 finished the whole 64 MiB size
  (3.197 s, 3.201 s) while PE 1 was stopped, at normal speed (11.47 and 11.57 ms per iteration). Each iteration ends in
  `nvshmemx_barrier_all_on_stream`, which needs PE 1's GPU. So the kernels and barriers PE 1's host had queued before the
  stop ran on its GPU through the IBGDA path `[measured timing, inferred cause]`.
- **The rule that separates the 2 wrong from the 5 correct trials.** The result is wrong exactly when PE 1 is the stopped PE
  and the stop spans the end of a size that is not the last one (16 or 32 MiB). The two wrong trials stopped PE 1 across the
  32 MiB end (bold). The two PE 1 stops that were correct began after the 32 MiB end and spanned only the 64 MiB end, after
  which no kernel follows. The three PE 0 stops are all correct, including e89250ce, whose stop spans the 32 MiB end. 7/7
  trials fit this rule, n = 7 `[measured]`.

### Mechanism (example code)

`ring-reduce.cu` with npes = 2 `[source]`:
- Kernel (lines 82-147): PE 1 waits for each chunk's signal (`nvshmem_signal_wait_until`, line 114), adds `dst += src`
  (line 119) and puts its `dst` to PE 0 (lines 124-125). PE 0 does not wait at all (`if (mype != 0)`, line 112). It puts its
  `src` into PE 1's `dst` with a signal (lines 124-125). The broadcast phase does nothing for 2 PEs (conditions at lines
  137 and 140).
- Host (lines 223-261), for each size: 2 warmup launches, each followed by `nvshmemx_barrier_all_on_stream`
  (lines 228-233); 150 timed launches with barriers (238-243); `cudaStreamSynchronize` (246); PE 0 prints the timing (247-251);
  each PE copies `dst` to the host and checks it (254-260). The loop then goes straight to the next size's first warmup launch.
  There is no barrier between one PE's validation and the other PE's next launch.

What happened in 37bd4c3d `[inferred, every step consistent with the measured times]`:
1. By about 0.85 s PE 1's host had queued all 32 MiB launches and was waiting in `cudaStreamSynchronize` (line 246). The
   SIGSTOP at 1.322 s froze it there.
2. Both GPUs finished the 32 MiB iterations. PE 1's `dst` then held the correct sums 2i, and PE 0's validation found its own
   `dst` correct (no PE 0 lines). PE 0 printed the 32 MiB line at 2.243 s.
3. PE 0 copied and checked its buffer, then launched the first 64 MiB warmup kernel. That kernel's puts write PE 0's `src`
   (value i) over PE 1's `dst[0, 64 MiB)` without waiting for anything (line 112). This includes the 32 MiB that PE 1 had not
   yet copied out. PE 0 then blocks in the warmup barrier, because PE 1's host has queued no more work.
4. SIGCONT at 6.467 s. PE 1 returns from `cudaStreamSynchronize`, copies `dst` (line 254) and reads i instead of 2i. Its
   first error line comes at 6.476 s, 9 ms after SIGCONT. Printing 8.4 million lines takes seconds. PE 1 then joins the
   64 MiB warmup barrier, which releases PE 0. The 64 MiB size is correct on both PEs, because both now advance together and
   no kernel follows the last size. PE 0 prints 64 MiB at 14.407 s.

Why stopping PE 0 cannot do this `[source, inferred]`: PE 1 writes into PE 0's `dst` only after it receives PE 0's put for
the same launch (line 114). PE 0 issues that put only after its own host has validated and launched. So PE 0's buffer is
never overwritten before PE 0 reads it. Only the PE whose incoming puts are not gated by its own progress (PE 1 for 2 PEs) is
exposed.

The library causes the brief named are excluded `[measured, inferred]`:
- A recovery or re-post that misfired: 0 rounds, 0 declines on both PEs, no fault line.
- A lost put: PE 1 would then have waited forever on the signal, which uses `NVSHMEM_CMP_EQ` with the phase.
- A duplicated or reordered put inside the 32 MiB size: PE 0 validated 2i, which can only come from PE 1's put after its add.
  So PE 1's `dst` was 2i after the add and was overwritten later by a put that carried PE 0's `src`. The only such put the
  program issues is PE 0's next-size launch.

### Conclusion

`[inferred, strongly supported by measured timing and counts, n = 7]` The silent wrong result is caused by the example,
not by the library. `ring-reduce` has a host-side race between PE 1's validation copy of `dst` and PE 0's next-size put into
the same buffer. A correct NVSHMEM implementation, including stock NVSHMEM 3.8.0 without the recovery layer, produces exactly
this result for this program whenever PE 1's host lags PE 0's host by more than PE 0's validation time at a size boundary.
The two properties it relies on are the defining properties of GPU-initiated RDMA and of CUDA streams: PE 0's put lands in
PE 1's memory without PE 1's CPU, and queued kernels run while the host is stopped. SIGSTOP made the lag seconds long. Any
host stall of PE 1 longer than PE 0's validation (not measured, at most a few tens of ms) at a size boundary would do the same.

### What would fix it

- **Example.** Put `nvshmem_barrier_all();` after the validation loop (after line 260), so that no PE launches size S + 1
  before every PE has copied its size-S result. Alternatives: validate into a copy taken before the size's last barrier, or
  use a separate `dst` per size.
- **Library.** Nothing. No transport-level mechanism can tell this program's write from a legitimate one.
- **Study.** The silent wrong result in X1/N5 is real and was scored as pre-registered. Its cause sits in the application.
  How to report it is for the main session (EXPERIMENT.md 13), not for this file.

## 2. GIN `ring_exchange` under a QP fault: 14 of 16 hung

### Evidence

`[measured]`, recomputed for all 16 `gin:qperr` trials:
- In every trial the hook moved 4 of 4 GIN QPs of the target rank to ERR, between 0.008 s and 0.115 s after the anchor
  (`GIN/FAULT: GDAKI fault fired ... moved 4/4`, for example `raw/d3b36aba/r0.log:56`).
- In the 14 hung trials (targets: rank 0 in 8, rank 1 in 6; hook delays 8–104 ms) **neither rank printed a single line after
  the fire**. No Q4 classification, no `GIN/TS` round, no watchdog. Both ranks were killed by the 60 s wall (`rc -9`,
  `harness_end wall`).
- The 2 transparent trials have the two latest hook delays, 114 ms (55fa6493, target 0) and 115 ms (5b41efa1, target 1).
  In both, the **non-target** rank classified a `RETRY_EXC` CQE (`fp=12/0x81`, `path=abortable cq=ring`, which is the poll
  inside `flush`) 3.68 s and 3.54 s after the fire: `raw/55fa6493/r1.log:33,35` and `raw/5b41efa1/r0.log:54`. That rank led
  a round, and the target rank answered as responder:
  - `55fa6493/r1.log:41` `recovered rank=1 peer=0 role=initiator` and `r0.log:60` `role=responder`;
  - `5b41efa1/r0.log:60` initiator and `r1.log:39` responder.
  The target rank never classified its own flush-error CQEs. Case 2 then reported 37 037 and 35 708 µs per batch instead of
  about 152: one batch absorbed about 3.6 s, spread over 100 batches. All four cases PASSED.
- Fault-free runs (63e81d2a, 6f1e1436, 80b0e284) finish all traffic 0.137–0.152 s after the anchor. Their four timed kernels
  together take about 42 ms.

### Code paths `[source]`

- Example (`kernels.cuh`): every kernel begins with a GIN barrier (`bar.sync`, lines 51, 87, 127, 157). Each batch posts
  puts (54-60) and calls `context.waitSignal(...)` for the peer's puts of that batch (62, 100, 133, 174). Only after that does
  it call `context.flush(...)` (63-65, 101-103, 134, 175). The host side (`main.cu:59-135`) only launches, synchronizes and
  checks.
- `waitSignal` (`nccl_device/impl/gin__funcs.h:1381-1392`) calls `waitRollingLessEq` (lines 85-107). That loop reads only the
  signal word and, every few steps, the devComm abort word (`testAbort`). It never touches a CQ. The GIN barrier waits through
  the same `waitSignal` (`impl/gin_barrier__funcs.h:114`).
- The CQ is read, and errors classified into a Q4 record, only by `flush` and request waits: `ncclGinApi_Flush`
  (`gin/gdaki/gin_gdaki.h:1553-1580`) leads to `waitImpl`, which leads to `tsPoll` (line 1044).
- Host side (`transport/net_ib/gdaki/gin_host_gdaki.cc`):
  - The Q4 watcher thread (`gdakiQ4Watch`, lines 1072-1110) reads only records the device wrote into the mailbox.
  - Its QP-state watch (QPWATCH, lines 1093-1110) is a diagnostic, off by default: `NCCL_GIN_Q4_QPWATCH_MS` defaults to 0
    (line 764), and every trial logs `qpwatch_ms=0`. It is also compiled out of production builds.
  - The watchdog (`gdakiTsWatchdog`, lines 2995-3048) looks only at a round already running, a firmware phase, or queued
    records.
  - Nothing on the host reads the CQ or the QP state while no round is running.

### Conclusion

`[inferred from source, consistent with 16/16 measured trials]` **The pilot hypothesis is confirmed, with one refinement.**
After the hook, the target's QPs are in ERR. The target's posted puts are flushed with error CQEs on its own CQ. The
non-target's puts to the target get no ACK and end in `RETRY_EXC` about 3.6 s later on the non-target's CQ. Both CQEs are
read only if a thread is inside `flush` at that moment. Because the signals of the current batch never arrive, both ranks
spin in `waitSignal` or `bar.sync`, so no thread reads either CQE. No Q4 record is published, the helper has nothing to act on,
and the run hangs until the wall.

The refinement: recovery started only when, at the fire, one rank had already received the peer's whole batch and was inside
`flush` with its own puts still un-ACKed. That rank then read `RETRY_EXC` about 3.6 s later. This happened only for the two
latest hook times, both during case 2's timed kernel. Once a round starts, it does not need the other rank's device threads:
in both recovered trials the target's threads never polled (it answered as responder), and the round re-posted and finished
`[measured]`.

### What the library would need

`hq` already has everything after detection: per-peer rounds, re-post plans, and abort words that `waitSignal` honours. What
it lacks is a detector that does not depend on the application calling `flush`. Options, best first `[inferred]`:
1. **Host-side QP-state watch in the existing watcher thread.**
   - Every 20–100 ms, outside a round, `QUERY_QP` each GIN QP. The code exists as QPWATCH; make it a production feature, run
     it under `opMu` and charge it to the firmware watchdog, as the scope check at `gin_host_gdaki.cc:2885-2895` already does.
   - On a QP in ERR, push a synthetic fault record. `gdakiTsTestSelfReport` (lines 2950-2971) already shows how: an
     `NCCL_GIN_Q4_KIND_ERR_CQE` record, then `gdakiTsPushFault`. The helper then runs the normal round.
   - The target side would see ERR at once. The non-target side would see it after its `RETRY_EXC`, which moves the QP to ERR.
   - Cost: 4 firmware queries per period per rank.
   - A host peek at the CQ ring for an error opcode, through a host mapping of the CQ buffer, would avoid the firmware command
     but needs that mapping `[unverified that one exists]`.
2. **A CQ peek inside `waitRollingLessEq`.** Every 2^k spins, check without consuming whether the context's CQs hold an error
   CQE, and if so publish the Q4 record as `tsPoll` does. This works without host help, but:
   - `waitSignal` names no peer, so the peek must cover every QP of the context;
   - it must not consume CQEs a concurrent `flush` owns (it would have to use the `tsPollEnter` gate);
   - it adds work to the hot wait loop.
3. A bounded `waitSignal` that, after a stall of N ms, dumps a wait-timeout record. The Q4 record kind for "device wait-timeout
   dump" already exists. The host could then query the QPs. This adds latency and still needs option 1 on the host.

## 3. NVSHMEM `ring-reduce` under SIGKILL: no error in 7 of 7

### Evidence

`[measured]`, all 7 valid `nvs:kill` trials (21a06d5e, 2f9ea2f0, 6fd46a59, 76712ff9, 929d7e4b, bdc23a73, d047aadd; 4 killed
PE 0 and 3 killed PE 1; the eighth scheduled kill, 20579d16, ended before the fault and is excluded):
- The survivor printed exactly one line after the kill: `[nvshmem-t1] PE<s> ... peer <k> library socket closed (FIN)`. It
  came 0.0–0.5 ms after the kill acknowledgement, for example `raw/21a06d5e/r1.log:89`.
- Then nothing, until the harness's 20 s grace killed the survivor 20.19–20.20 s after the kill.
- No `FAULT`, `DECLINE` or `marked failed` line in any of the 7.
- The library socket exists in every run. It is created by the library itself (`ibgda.cpp:6729`, the
  `library socket on ...: listener port ..., connected to 1 peer(s)` line printed at start-up on both PEs), independently
  of the bootstrap plugin.

### Code paths `[source]`

All in `<scratch>/agent_t1_380/src/src/modules/transport/ibgda/ibgda.cpp`.
- `t1_peer_fin` (lines 6432-6444) records a clean FIN as "peer process gone".
- The FIN feeds a decision only inside `t1_fault` (lines 7681-7745). There, `RETRY_EXC` with FIN is declined with "RETRY_EXC
  and the peer's library socket shows FIN (peer process gone)". `t1_fault` runs only for a device record or a scan hit (helper
  loop, lines 7783-7800).
- The helper loop (lines 7812-7826), on finding FIN, only logs `library socket closed (FIN)` and skips that peer from then on.
- `t1_scan` (lines 7748-7781) reads device-side sticky error state that a device thread set after polling an error CQE. It
  does not read the CQ itself.
- `t1_decline` (lines 6790-6845) moves the QPs to ERR, fails the gates (posters and `quiet`), logs and marks the transport
  failed. It does not touch signal waits.
- Device waits are stock and unmodified by the t1_380 diff:
  - `nvshmem_signal_wait_until` (`src/include/device/nvshmem_defines.h:583-587`) calls `nvshmemi_wait_until`
    (`non_abi/device/wait/nvshmemi_wait_until_apis.cuh:137`), a bare `while (*addr ...)` loop. Its only optional check is
    `NVSHMEM_TIMEOUT_DEVICE_POLLING`, which is OFF in this build (start-up config lines in every `r0.log`).
  - The device barrier (`non_abi/device/coll/barrier.cuh:266-289`) runs `quiet` and then a dissemination sync that spins on
    pSync the same way.

### Answer to "does death detection depend on a helper socket the bootstrap does not create?"

**No** `[measured]`. The library socket was up and saw the FIN within 0.5 ms in 7/7.

### Conclusion

`[inferred from source and 7/7 measured trials]` The death is detected but never acted on:
1. **The verdict is gated on a device fault record.** FIN is used only as corroboration inside `t1_fault`, which needs an error
   CQE that a device thread polled. The survivor has nothing in flight and is not polling. When PE 0 dies, PE 1 spins in
   `nvshmem_signal_wait_until` for PE 0's next chunk or in the barrier sync. When PE 1 dies, PE 0 spins in the barrier sync
   waiting for PE 1's arrival, after its own puts and barrier signal were already ACKed by the still-alive peer. So no error
   CQE is produced, or if a late write produces one, nobody reads it.
2. **Even a verdict would not release the application.** The waits it is stuck in have no abort check. This is measured in
   the same run: in all 8 `nvs:remacc` trials both PEs printed `FAULT ... -> decline` / `DECLINE` / `marked failed`
   5–8 ms after the fault (for example `raw/26186903/r0.log:125-127`, `r1.log:89-90`), and both still hung until the 60 s
   wall.

The earlier t1_380 kill cell (R9, 5/5 declined) differs only in its driver, which kept posting puts in a loop. The survivor
therefore met `RETRY_EXC` and the FIN rule fired. Its scored decline reason was "RETRY_EXC and the peer's library socket
shows FIN (peer process gone)" (`harness/gpu-initiated/nvshmem_ft/t1_380/results/20261008/trials_scored.csv`, rows R9)
`[measured, earlier study]`.

### What would fix it

1. **Host-side death verdict.**
   - In the helper loop, treat a FIN that was not preceded by an orderly goodbye as death: call `t1_decline(peer, ...,
     "peer's library socket closed (FIN) without goodbye", false)` at once.
   - Every normal run ends with the same FIN at teardown (for example `37bd4c3d/r1.log:291`). So the closing side must first
     send a goodbye message (a new message type) from teardown, or the helper must ignore FIN once this PE is itself in
     finalize.
   - This alone would put a DECLINE line in the log within about 1 ms, which meets the "error within 3 s" part of the kill
     prediction (N4).
2. **Make a decline reach the application.**
   - Option one: a device-visible failed word, which t1 already keeps as the host-mapped mirror that `t1_hflag_fail` writes.
     It would be checked every N spins inside `nvshmemi_wait_until*` and the barrier's sync wait, and on failure would return
     with an error or `__trap()`, so the host's `cudaStreamSynchronize` fails.
   - Option two, a fail-stop policy for applications that cannot handle errors: after a decline, the library prints the reason
     and exits non-zero after a short bound.
   - Without one of these, every decline in this example ends as a hang (8/8 `remacc`).

## 4. DDP silent receive-QP fault: recovered in 6 of 6

### Evidence

`[measured]`, all 6 `ddp:srq` trials:

| trial | target (receiver) | k | receiver sees its own flush error | sender's `RETRY_EXC_ERR` after hook (s) | R_done / fifoHead | replayed sends | recovery total (ms) | final hash, both ranks |
|---|--:|--:|---|--:|---|--:|--:|---|
| 37f61f7b | 1 | 2888 | yes, does not notify | 3.760 | 2888 / 2890 | 2 | 2.086 | `9d051c49d3ebdcc3` |
| 55f19881 | 1 | 1478 | yes, does not notify | 3.697 | 1479 / 1481 | 2 | 1.937 | same |
| a27938a8 | 0 | 405 | yes, does not notify | 3.601 | 407 / 409 | 2 | 2.125 | same |
| a5497f6d | 1 | 1173 | yes, does not notify | 3.664 | 1173 / 1176 | 3 | 2.022 | same |
| b3596cab | 0 | 774 | yes, does not notify | 3.605 | 775 / 777 | 2 | 2.017 | same |
| fb20e695 | 0 | 1879 | yes, does not notify | 3.567 | 1880 / 1881 | 1 | 1.954 | same |

Example lines:
- receiver `raw/37f61f7b/r1.log:113-117`: the hook, `recv comm: incident via cqe: status=5(WR_FLUSH_ERR) ...`, then
  `drained; SILENT test mode: not notifying the leader`;
- sender `raw/37f61f7b/r0.log:356` `send comm: incident via cqe: status=12(RETRY_EXC_ERR) vendor_err=0x81
  peer=no-evidence-of-death -> lead a recovery` and `:358` `recovered (epoch 1, round 1) ... replayed 2 ... total 2.086 ms`;
- receiver `r1.log:119` `re-posted 2 receive(s)`.

Rank 0's longest output gap in these trials is 3.57–3.78 s (`max_gap0`), i.e. training stalled for one `RETRY_EXC` interval.
The hashes equal the reference on both ranks in 6/6.

### Mechanism

`[source: DESIGN_stage2.md:344, 458-471; net_ib_stage2.diff:165, 576-577, 1197; measured above]` The silent-receive hook
forces the receiver's QP to ERR right after its k-th receive completion and suppresses the receiver's notification. Before
that completion, the receiver had already granted the sender 1–3 more slots (fifoHead − R_done). NCCL keeps several steps
of a large message posted ahead, and DDP's gradient buckets span many steps. So the sender posted those RDMA writes into the
dead QP, got no ACK, and after the retry budget (`NCCL_IB_TIMEOUT=14`, 3.57–3.76 s on these NICs) received
`RETRY_EXC_ERR` on its own send CQ. NCCL's CPU proxy thread polls that CQ continuously, so the error was read at once. Stage 2
classifies `RETRY_EXC` with no evidence of death on the send side as "lead a recovery". The leader re-established the QP pair,
the receiver re-posted its receives, and the leader replayed the unacknowledged sends: exactly-once, 2 ms.

### Why a hang was predicted

The prediction (D4) carried over the earlier result "silent receive fault, 256 KiB all-reduce: hung until the time limit
5/5" `[measured, earlier study]`. In that workload the k-th completion came at the end of an iteration, the sender had sent
everything it had grant for, and it then waited for a grant that never came. DESIGN_stage2.md:458 records the lesson: "A
silent responder death is only visible to a sender that sends." The same earlier work found that on a 64 MiB broadcast the
sender met `RETRY_EXC` 1 time in 3.

In DDP most receive completions fall in the middle of a multi-step bucket, so a further grant is almost always outstanding.
The one DDP hang seen so far fits the exception: pilot P3 `demo-ddp-srq-top`, k = 2912 at iteration 242, stuck in an
all-reduce of `NumelIn=262400` (about 1 MiB, DDP's small first bucket). There, no `RETRY_EXC` appeared and torch's 30 s
collective timeout ended both ranks (`results/pilot/raw/demo-ddp-srq-top`) `[measured, n = 1]`.

### Conclusion and fix

`[inferred, measured 6/6]` The DDP result was recovered by Stage 2's sender-led recovery from the sender's own `RETRY_EXC`
CQE. That path exists because the CPU proxy, not the application, owns CQ polling. No fix is needed. The "silent" variant
exists only as a test switch (`NCCL_RDMA_FAULT_INJECT_RECV_SILENT`). Without it the receiver drains and notifies the leader
itself, which is the `rqp` cell, 10/10 transparent in this run (prediction D3). A hang stays possible
when the fault lands on a completion after which the sender holds no grant (pilot 1/3 demos). Torch's 30 s timeout then bounds
it, as D4 assumed.

## Limits of this analysis

- Nothing was run. The NVSHMEM race is shown by timing and counts (7/7 trials fit the rule, exact mismatch count), not by
  rerunning a patched example. The cheapest confirmation would be a pilot run with `nvshmem_barrier_all()` added after
  validation and a stop of PE 1 across the 32 MiB end. It should then be correct.
- For the NVSHMEM wrong data, values are logged for indices 1–200 only. "All 8 388 607 hold i" is inferred from the count and
  the mechanism.
- PE 0's validation time, which sets how large a PE 1 stall exposes the race, was not measured.
- For GIN, which code each rank was in at the fire is inferred from the source and the two recovered trials. The 14 hung trials
  print nothing after the fire.
- The option lists under "what would fix it" are design suggestions, not implementations.
