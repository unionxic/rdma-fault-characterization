# Transparent recovery, step S2: GIN GDAKI with many operations in flight

Patch: `gin_transparent_s2.diff`, a full diff against NCCL v2.32.3-1 (the four earlier layers, S1 and S2,
with the review fixes). Driver: `gin_ts2.cu`, an extended copy of `gin_ts1.cu` that still contains no
recovery code. Gate micro-test: `gate_ce_test.cu`. Minimal bidirectional program: `gin_bidir_min.cu`.
Scripts: `scripts/ts2/`. Results: `results/20260930_ts2/` (first S2 build: A latency and gate test, B,
C, E) and `results/20261001_ts2/` (reviewed build: S1 regression cells, D, the review cells, the
16…1024-thread cells with n = 10, latency again, the bidirectional diagnostics). Each table names its
build.

Tags: **[measured]** means counted from the per-trial logs by `scripts/ts2/rows.py` and `summarize.py`;
**[source]** means read in the code; **[inferred]** means reasoned but not tested.

A run is **transparent** when all of the following hold:
- every flush returned `ncclSuccess` and all iterations ran;
- every slot was bit-exact, both on the GPU when its signal arrived and on the host at the end;
- every final signal was exact;
- neither host saw an async error.

Faults:
- F1: NCCL's test hook forces the initiator's QPs to ERR.
- F3: the hook forces the peer's QPs to ERR, so the initiator sees RETRY_EXC after about 3.6 s.
- F2: the application's own out-of-bounds put.
- F4: SIGKILL of the peer.

Setup: rank 0 is rain and rank 1 is sunny, with GPU-rung doorbells and IB timeout 14. Unless a cell says
otherwise, rank 0 sends and rank 1 receives. Each table names the build it comes from: "first build"
(30 Sep, `results/20260930_ts2`) or "final build" (the reviewed build with every fix of 1 Oct,
`results/20261001_ts2`; the trials of two intermediate builds of that day are kept under
`results/20261001_ts2/prev_6ff74bb6` and `smoke7`, see Provenance). The `smoke*` directories are
earlier builds, kept only for reference.

## Results

### A. One gate word per QP

**Gate micro-test** [measured] (`gate_test.txt`). A copy-engine 4-byte write races SM 64-bit atomics
on the same word. The host runs quiesce and publish cycles back to back. Each run lasts 10 s:

| threads | entry | rain (sm_75): quiesce rounds / entries | sunny (sm_86): quiesce rounds / entries | lost CE writes | lost increments | Dekker violations | thread inside while epoch odd |
|---|---|---|---|---|---|---|---|
| 32 | add, GPU scope | 16 986 / 4.5e8 | 16 964 / 4.3e8 | 0 | 0 | 0 | 0 |
| 2 048 | add, GPU scope | 16 994 / 1.1e10 | 16 951 / 1.1e10 | 0 | 0 | 0 | 0 |
| 16 384 | add, GPU scope | 17 003 / 1.1e10 | 16 956 / 1.1e10 | 0 | 0 | 0 | 0 |
| 16 384 | add, system scope | 16 922 / 1.1e10 | 16 891 / 1.1e10 | 0 | 0 | 0 | 0 |
| 16 384 | CAS loop (the late-failure path) | 4 879 / 1.2e7 | 5 322 / 6.0e6 | 0 | 0 | 0 | 0 |
| 16 384, 2 µs inside | add, GPU scope | 16 982 / 1.1e10 | 16 958 / 1.1e10 | 0 | 0 | 0 | 0 |
| 163 840 | add, GPU scope | 16 625 / 1.1e10 | 16 583 / 1.1e10 | 0 | 0 | 0 | 0 |

- All 14 runs passed. An earlier 5 s pass on the smoke build passed 12 of 12 (`gate_smoke.txt`).
- The Dekker check: once the host has written an odd epoch and read a count of 0, no thread may enter
  with the old epoch. The per-epoch counter of entries must not grow after that point.

**Fault-free latency** [measured] (`results/20261001_ts2/trials_lat.csv`, reviewed build; the first
build's numbers in parentheses, `results/20260930_ts2/trials_lat.csv`):
- The same application source is compiled against each build.
- Each cell is put + signal + flush, 3000 iterations per run, 5 interleaved runs. The table shows p50,
  median of runs.
- One S2-on 256 KiB run (reviewed build) and one S1-off 4 KiB run (first build) were lost to the
  driver's rendezvous port being taken, so those cells have 4 runs.
- The reviewed build adds one load of the gate's error record per post (`tsPostLeave`).

| size | gpudb v2 | S1 off | S1 on | S2 off | **S2 on** | S2 on, gate at system scope |
|---|---|---|---|---|---|---|
| 4 KiB | 10.24 µs | 10.27 | 16.80 | 10.24 | **10.91** (+0.67 µs, +6.5%; first build 10.85) | 12.29 |
| 256 KiB | 38.40 µs | 38.50 | 41.73 | 38.56 | **38.96** (+0.56 µs, +1.5%; first build 38.94) | 39.94 |

The gate micro-test passed 14 of 14 runs again on the reviewed build (`results/20261001_ts2/gate_test.txt`).

**S1 correctness cells on the S2 build** [measured] (reviewed build, `results/20261001_ts2/trials_reg.csv`,
`rounds_reg.csv`; the first build gave the same counts):

| cell | n | outcome |
|---|---|---|
| fault-free | 10 | transparent 10/10 |
| F1 | 10 | transparent 10/10; 2 WQEs re-posted per round |
| F3 (RETRY_EXC) | 10 | transparent 10/10; fault → resumed 3.68 s [3.57–3.76] |
| F1 ×5 in one run | 10 | transparent 10/10, 50 rounds (the third fault hits the re-posted WQEs) |
| F1 inside an in-flight op (4 KiB back to back) | 30 | transparent 30/30; re-posted n = 0 in 21 rounds, n = 2 in 9 |
| F2 (REM_ACCESS) | 10 | declined 10/10 ("class REM_ACCESS is not recoverable"); `ncclRemoteError`, async error on both ranks; rank 1's abort does not return (exit 7, as in S1) |
| F4 (SIGKILL) | 10 | declined 10/10, 3.59–3.82 s after the kill ("RETRY_EXC and the peer's socket shows FIN/RST") |
| negative control: no ticket rebase | 10 | fails as predicted 10/10 (`ncclTimeout`, slots missing) |
| negative control: no host doorbell | 10 | fails as predicted 10/10 |
| flag off, S2 build / gpudb build | 5 / 5 | `ncclRemoteError` at the fault, 5/5 each (Q4 behaviour) |

- The F1 round takes 10.31 ms [10.12–10.75] (S1: 9.46; first S2 build 10.42):
  - quiesce 0.21 ms;
  - Prepare 0.47 ms;
  - REQ→ACK 6.03 ms (S1: 5.28; the responder now also reads the ring indices and looks its GID up);
  - Commit 3.34 ms;
  - re-post 0.18 ms.

### B. Many operations in flight, many posting threads

Cells, with the fault placed in the traffic by `NCCL_GIN_FAULT_INJECT_AT`:
- `burst` cells: one thread per iteration posts K = 16 puts of 4 KiB, then one signal, then one flush.
  The puts are aggregated (one doorbell) unless marked "not aggregated".
- `mtb` cells: 2 CTAs × 2 threads each post 8 aggregated 2 KiB puts + a signal + a flush.
- `mt<P>` cells: P threads each post a put + signal + flush. Up to 256 signals are used; above that,
  signals are shared and checked at the end.

| cell | n | transparent | WQEs re-posted per round (faulted QP) | notes |
|---|---|---|---|---|
| burst, F1 | 10 | 10/10 | 0, 0, 9, 17 ×7 | |
| burst, F1, not aggregated | 10 | 10/10 | 0, 0, 0, 2, 4, 8, 11, 15, 17, 17 | prefixes that end inside a burst |
| burst, F3 | 10 | 10/10 | 4, 17 ×9 | |
| burst, F1 + a second F1 inside the first commit | 10 | 10/10 | 20 rounds; each second round found none of the re-posted WQEs executed and re-posted them all (n = S: 17 ×9, 9 ×1) | a fault on the re-posted WQEs |
| 2 CTAs × 2 threads, F1 | 10 | 10/10 | 0, 3, 3, 12, 13, 36 ×5 | |
| 2 CTAs × 2 threads, F3 | 10 | 10/10 | 16, 36 ×9 | |
| 16 threads, F1 (final build) | 10 | 10/10 | MT16_N | |
| 64 threads, F1 (final build) | 10 | 10/10 | MT64_N | ring full |
| 256 threads, F1 (final build) | 10 | 10/10 | 234–265 | 1 234 WQEs taken from the rescue area; all 10 re-posts chunked |
| 1024 threads, F1 (final build) | 10 | 10/10 | 563–725 | 5 282 WQEs from the rescue area; all 10 re-posts chunked; the trigger was lowered so that it lies inside the 100-iteration run (the first formula put 4 of 10 triggers past the end) |
| fault-free (burst, 2×2 on the first build; 16/64/256/1024 threads on the final build) | 3 each (1024: 2, one lost to the rendezvous port) | 17/17 | – | |

The 16…1024-thread F1 rows are from the final build (`results/20261001_ts2/trials_b.csv`, holds `b4a`
and `fix1`; the first build's n = 5 runs gave 20/20 and are in `results/20260930_ts2`). The burst and
2×2 rows are from the first build; those paths did not change in the review fixes.

- Every signal was applied exactly once: the final value was exact on every signal of every run.
- Data were bit-exact on the GPU and on the host.
- No async error was seen.
- The helper round took 10.2–10.9 ms (median per cell), 12.0 ms with 256 threads and 17.3 ms with 1024
  threads (the chunked re-post).
- The path that rings aggregated WQEs left unrung before Prepare was needed in 0 of the 180 rounds above
  (90 initiator and 90 responder rounds).

### C. Symmetric initiation

Setup:
- Rank 0 posts 4 KiB back to back.
- The hook forces the QPs of both ranks to ERR. Rank 1's delay is 1–2 ms shorter, the offset at which
  both helpers started within about 1 ms of each other in the calibration hold `smoke6`.
- Rank 1's helper receives a LOCAL_QP_ERR record when its hook fires (test knob
  `NCCL_GIN_TS_TEST_SELF_REPORT`), so both helpers start a round.

| cell | n | transparent | both helpers initiated at once | declined |
|---|---|---|---|---|
| tie-break on (S2) | 30 | **30/30** | 28: the lower rank kept its round, the higher rank yielded and answered it; 2 were sequential rounds | 0 |
| tie-break off (S1 behaviour) | 10 | 1/10 | 9: NACK, and both sides declined ("simultaneous recovery from both ends") | 9 |

**Two GIN kernels per GPU, launched on two streams, do not run at the same time on this testbed when the
receiver is launched first; one kernel with both roles does** [measured] (`trials_c.csv`;
`results/20261001_ts2/trials_min.csv`, `summary.md` "bmin", `two_streams*.txt`).

What the driver's `bidir` cells showed (two kernels per rank, receiver launched first on its own stream;
6 of 6 trials in `c1`, 27 of 27 in `bmin4`–`bmin6`, S2 flag on, flag off and the gpudb build alike):
sunny → rain delivered 120/120 slots and its signal exactly; rain → sunny got success CQEs for 24–28
puts and then a remote NAK (REM_ACCESS) from sunny's NIC; sunny's receiver saw 0–2 slots. With no kernel
preload (`smoke1`) the roles were reversed. Rain's receive path is therefore not the cause.

The minimal program `gin_bidir_min.cu` (four windows, one per direction and side; one signal per
direction; a context per direction; checks on the GPU at arrival and on the host at the end; CUDA events
after each kernel) on the **unpatched gpudb build**, 64 B × 120 and 256 KiB × 64:

| mode | n | ok | evidence |
|---|---|---|---|
| one direction alone (`d01` rain → sunny, `d10` sunny → rain) | 10 + 9 | 19/19 | |
| both directions, sequentially (`seq`) | 3 | 3/3 | |
| both at once, no receiver kernels (`hostrx`: the host polls the signal; `txonly`: checked after a barrier) | 3 + 3 | 6/6 | |
| **both at once, a sender kernel and a receiver kernel per GPU, receiver launched first** (`both`, also on one context) | 13 + 3 | **0/16** | on both GPUs the sender kernel ended 1–3 ms after the receiver kernel, i.e. at the receiver's timeout (8.2–8.4 s), in 13 of 13 timed trials; the launch call returned in 0–2 ms; the same with the sender launched 2 s later (3/3), with a 1-thread receiver (3/3), with `CUDA_MODULE_LOADING=EAGER` (6/6), with `CUDA_DEVICE_MAX_CONNECTIONS=32` (6/6) and with the local-memory reservation raised to 2 KiB (6/6; the kernels' frames are 248 and 592 B). The sender kernel did not execute until the receiver kernel exited |
| **both roles as two CTAs of one kernel** (`fused`; gpudb and S2 builds) | 6 + 3 | **9/9** | both kernels' work done in 2–7 ms |
| sender launched first, then the receiver (`txfirst`), and the same with the sender paced to 50 ms per put | 3 + 3 | 6/6 | paced: the receiver kernel saw its first signal 0–2 ms after its entry and its last 5.95 s after, while the sender kernel was still running: a GIN receiver kernel does run next to a GIN sender kernel |
| two plain kernels on two streams (`two_streams_test.cu`, a 2 s spinner then a trivial kernel, both launch orders, both GPUs) | 4 | concurrent 4/4 | with stack frames of 256 B / 1 KiB / 4 KiB as well; only a kernel whose frame exceeds the device's local-memory reservation (4 KiB against the 1 KiB default) waits for the running kernel, which is the documented CUDA behaviour and not this case |

- So the loss is not in the network path: the direction whose receiver kernel was launched first
  simply has no running sender on the other side until that receiver gives up; the late sender's
  puts then land in a process that is tearing down, hence the REM_ACCESS. Why the GPU does not start a
  GIN sender kernel while a GIN receiver kernel runs (plain kernels do start, and a GIN receiver does
  start next to a GIN sender) was not found; lazy module loading, the local-memory reservation and the
  number of hardware queues were excluded by direct tests. It is the same on the unpatched build, so it
  does not come from the recovery code.
- A real GIN application runs both roles in one kernel. The driver's `GIN_TS_BIDIR_FUSED=1` does the
  same (block 0 sends, block 1 receives), and C was run with it.

**C with real bidirectional traffic** [measured] (reviewed build, `results/20261001_ts2/trials_c.csv`,
holds `c4` and `c5`): every rank sends 120 × 256 KiB to the other and receives the other's, as two CTAs
of one kernel per rank; the hook fires on both ranks (F1both) at the same delay after context creation,
or on one rank (F1, F3). No self-report knob.

| cell | n | transparent | rounds | notes |
|---|---|---|---|---|
| fault-free, gpudb build / S2 flag off / S2 flag on | 3 / 3 / 5 | 11/11 | 0 | both directions bit-exact, both signals exact |
| F1 on both ranks at once | 20 | **20/20** | 20 initiator + 20 responder | rank 1's hook fired 0.6–1.0 ms after rank 0's in every trial; the later rank's helper always found the REQ first and answered it, so the tie-break was not needed (0 kept / 0 yielded). Each round re-posted both sides' unexecuted WQEs (initiator n = 0 or 2) |
| F1 on rank 0 only / F3 (rank 1's QPs forced to ERR) | 4 / 5 | 9/9 | 1 each | one F1 trial lost to the rendezvous port |
| F1 on both, tie-break off | 5 | 5/5 | 5 + 5 | no overlap, as above, so S1's NACK path was not reached |
| **F1 on both with rank 1's hook 1–2 ms earlier, 4 KiB back to back both ways** (`bidirf_sym_b`, the symmetric-initiation test with real traffic) | 20 | **20/20** | 20 initiator + 20 responder | both helpers initiated at once in 19 of 20 (rank 1's fault fired 0.05–1.64 ms before rank 0's): the lower rank kept its round and the higher rank yielded and answered it, 19 kept / 19 yielded; 1 trial had sequential rounds. Helper round 8.9 ms, fault → resumed 10.7 ms [9.95–11.45] |
| the same, tie-break off (S1 behaviour) | 5 | 1/5 | – | 4 declined on both sides ("simultaneous recovery from both ends"), 1 had no overlap |

The symmetric-initiation result with the test knob (first table of this section) therefore holds with
real bidirectional traffic and faults on both sides, without any knob.

### D. Address flap on GIN (a real path fault)

Setup:
- `gid_blackhole.sh` gives each node a secondary RoCE address. The test QPs use its GID, selected with
  `NCCL_IB_GID_INDEX` per node.
- Sunny's secondary address is removed 2 s after launch for 0.5, 6 or 15 s, then re-added.
- The application sends 16 KiB every 15 ms for 1800 iterations.

| cut | build | n | transparent | declined | GID index after re-add | first error (RETRY_EXC) after cut start | resumed after cut start | slow iteration |
|---|---|---|---|---|---|---|---|---|
| 0.5 s | S1 | 2 | 0 | 2 | moved 2/2 | 3.94, 4.02 s | – | – |
| 6 s | S1 | 2 | 0 | 2 | moved 2/2 | 3.94, 3.95 s | – | – |
| 15 s | S1 | 2 | 0 | 2 | moved 2/2 | 3.94, 3.96 s | – | – |
| 0.5 s | S2 | 5 | **5/5** | 0 | moved 5/5 | 3.88–4.06 s | 3.89–4.07 s | 3.62–3.80 s |
| 6 s | S2 | 5 | **5/5** | 0 | moved 5/5 | 3.82–4.04 s | 6.29–6.32 s | 6.02–6.05 s |
| 15 s | S2 | 5 | **5/5** | 0 | moved 5/5 | 3.78–4.02 s | 15.30–15.31 s | 15.02–15.05 s |
| 20 s (near the bound) | S2, reviewed build | 3 | **3/3** | 0 | moved 3/3 | 3.91–4.01 s | 20.29–20.31 s (GID wait 16.29–16.38 s) | 20.03–20.05 s |
| 30 s (beyond the bound) | S2, reviewed build | 3 | 0 | **3/3, clean** | – | 3.87–4.01 s | – (sunny's GID wait ended at its 21.0 s bound: "not back after 21 010–21 019 ms"; sunny declined, rain got NACK and declined 24.9 s after the cut began; no watchdog surface; both aborts returned, 0.56–0.98 s on rain and 6.3 s on sunny, whose receiver kernel first ran out its own 40 s wait) | – |

- **The GID index moves on every re-add** [measured]. Sunny's secondary address alternated between index
  5 and 6 in 21 of 21 cuts, and in 6 more cuts made while no test process was running
  (`d1_setup_failed`).
- **The QPs do not survive even a 0.5 s cut** [measured]. Their address vector still names the old
  index. RETRY_EXC fires about 2.9 s after the address is back, about 3.9 s after the cut begins.
- **S1** declines about 4 s after the cut start:
  - the responder's reconnect fails with the stale source GID index ("commit failed"; DOCA resolves the
    next hop from that index at RTR [source]);
  - the initiator gets NACK;
  - the flush returns `ncclRemoteError` and both hosts see the async error.
- **S2** looks each rank's own GID up again by value before the reconnect.
  - 0.5 s cut: sunny found its address at the new index in 0.3 ms.
  - 6 s cut: sunny waited 2.23–2.46 s for the address.
  - 15 s cut: sunny waited 11.28–11.52 s.
  - Rain's index never changed.
  - In every run the application saw one slow iteration and nothing else.
- Sunny's nvme error-line count stayed at 0 in every flap hold. Both secondary addresses were gone after
  every teardown (`gbh_*.txt`).

### R. Review cells (reviewed build, `results/20261001_ts2/new`)

The code review of the first S2 build found four items (see "Review fixes" below). These cells test the
fixes. `ring_*`: one thread posts 128 aggregated 1 KiB puts (the whole 128-slot SQ, none rung) and then
one signal, which must wait for the slot of the first put, whose WQE was never rung; stock DOCA would
spin there forever. `burst_hring*`: 16 aggregated 4 KiB puts, a 20 ms pause, then the signal that rings
for them; the local fault lands in the pause.

| cell | n | outcome | kernel exited / abort returned (rank 0) | fault record path, class |
|---|---|---|---|---|
| full ring, fault-free | 5 | transparent 5/5 (the slot wait rang the 128 puts itself after 16 K spins; 5.5 ms per iteration) | 5/5 / 5/5 | – |
| full ring, F4 (SIGKILL of rank 1) | 5 | declined 5/5 ("RETRY_EXC and the peer's socket shows FIN/RST") | 5/5 (exit 4) / 5/5, abort 0.69–1.00 s | `post-slot-wait`, RETRY_EXC, 5/5 |
| full ring, F2 (invalid remote offset at iteration 10) | 5 | declined 5/5 ("class REM_ACCESS is not recoverable") | 5/5 (exit 4) / 5/5, abort 0.81–0.83 s | `post-slot-wait`, REM_ACCESS, 5/5 |
| host ring of unrung WQEs, fault in the pause (`burst_hring_b`) | 5 | transparent 5/5, 17 WQEs re-posted per round; **host-rung WQEs: 0 of 5 rounds** — the helper learns of the fault only when the poster's next post (the signal) fails, so the puts were rung by then | 5/5 / 5/5 | flush, LOCAL_QP_ERR |
| the same with the self-report knob (`burst_hring2_b`: the helper starts its round while the poster is still in the pause) | 5 | transparent 5/5; **the host rang 16 unrung WQEs in 5 of 5 rounds** and re-posted exactly those 16 (n = 16, not a multiple of the 17-WQE burst); exactly-once held (signals exact 5/5); helper round 10.6 ms, fault → resumed 12.1 ms | 5/5 / 5/5 | self-report (LOCAL_QP_ERR) |

- On the intermediate build (the ring condition fixed, nothing else), the two faulted full-ring cells hung:
  the kernel never exited and the application's watchdog ended both ranks (exit 7, 1 of 1 each,
  `smoke7`). The cause and fix are under "A slot wait that consumes the error CQE" below.
- The poster-side report exposed a second weakness (`b4b`, 256 threads, F1: 1 of 10 declined with
  "class OTHER is not recoverable"): the report named the newest WQE as its ticket, the one-ring window
  behind it held no CQE of the current lap yet, and the classifier read the CQE of an earlier lap at
  that slot as the root. Fix: the report's ticket is the CQ's software consumer index (the slot wait
  never advanced it past the error, so the window starts at the root), and a window with no current
  CQE at the ticket is not classified from the slot's stale contents (the record from the slot wait is
  used instead; `root_src=stale` in the log). The 256- and 1024-thread F1 cells, the full-ring cells and
  the host-ring cell were re-run on the final build (`fix1`; the earlier 256/1024 runs are in
  `b/superseded`). The 1024-thread F1 cell's trigger also had to be lowered: with 100 iterations the
  first formula put 4 of 10 triggers past the end of the run (no fault, trivially transparent).

### E. The post-commit residual

Setup: hold 4 s. The initiator's helper stalls after marking the round PUBLISHING (`pub_*`), or after its
commit point but before the mark (`late_fail`).

| cell | n | outcome |
|---|---|---|
| stall 10 s after PUBLISHING | 5 | **transparent 5/5**. The device threads' second bound expired at 8 s, they saw PUBLISHING and kept waiting. The slow iteration was 10.01 s. S1 would have failed them at 8 s while re-posting anyway [inferred] |
| stall 14 s after PUBLISHING | 5 | flush failed at 12.00 s = 3 × hold, 5/5. The helper re-posted at 14 s, then the idle scan declined and the async error surfaced. This is the remaining residual: it needs a helper that stalls for 2 × hold inside its re-post |
| stall 12 s after the commit point, before PUBLISHING | 3 | flush failed at 8.00 s = 2 × hold, 3/3. The helper saw the device failure at its PUBLISHING check and declined without re-posting (as S1's `late_fail_b`) |

## What changed versus S1, and why

### A. The gate
- **The gate word.** S1 used two counters, each entered with `atomicAdd; fence.sc.sys; ld.acquire.sys`
  plus a `status` load. S2 uses one 64-bit word per QP, in the QP's 8-byte `reserved1` padding.
  - Epoch half: written only by the host, as one 4-byte copy. Even = stable, odd = a recovery owns the QP.
    Bit 31 = declined. Bit 30 = PUBLISHING (see E).
  - Count half: written only by the device. It counts the threads inside a post or a CQ poll. Bit 31 = a
    device thread failed the QP; it is set only by an atomic OR or CAS, so a host write of the other half
    cannot clear it.
- **Device side.** Entry is one `atom.acquire.gpu.add.u64`, whose return value carries the epoch. Leave
  is one `red.release.gpu.add.u64 -1`. There is no fence.
- **Host side.** Quiesce copies an odd epoch into the epoch half, then reads the word until the count is
  0. Publish copies the new even epoch.
- **Why it is correct.** Both sides act on the same word, so the word's coherence order decides:
  - an add ordered before the host's write returns the even epoch and is counted when the host reads;
  - an add ordered after it returns the odd epoch and backs out.

  This needs the copy engine's partial write and the SM's 64-bit RMW to be coherent on that word. The
  micro-test checks exactly that; the copy engine is outside the PTX model [inferred otherwise].
- **The other words.** `commit`, `abandoned`, `lbase`, `nonmsg` and `reported` moved to `reserved2`.
  They stay off the fast path.
- **Scope.** GPU scope is used. System scope costs 1.4 µs more at 4 KiB [measured] and gave the same
  micro-test result.

### B. Many operations in flight
- **Aggregated posts.** They leave WQEs reserved and ready but not rung. When the count is 0, the host
  rings them into the ERR QP: the NIC flushes them, Prepare's checks and drain hold, and they are
  re-posted like any unexecuted WQE [source; not needed in any measured round].
- **Blocked posters overwrite WQEs that must be re-posted.** A poster blocked on a full SQ ring (128
  WQEs) takes its slot as soon as the NIC flushes the WQE in it. That overwrites a WQE the recovery
  must re-post, and S1 declined such a round. S2 changes the slot wait of a gated QP, in NCCL's vendored
  DOCA header:
  - it copies such a WQE into a per-QP rescue area first (32 rings deep by default);
  - it polls the slot's CQE directly (owner parity + WQE counter) instead of through DOCA's
    `[cqe_ci, cqe_ci + cqe_num)` window. That window stops moving at the first error CQE and would strand
    posters more than one ring ahead;
  - it rings ready aggregated WQEs it is waiting for: at once while a recovery quiesces the QP (odd
    epoch) or has failed it (bit 31 of the epoch half: a decline writes it with an even epoch, and the
    QP is in ERR, so the ring gets the poster its error CQE and the kernel can exit), and otherwise
    after 16 K spins (a WQE that was never rung completes only when rung, and nobody else rings while
    its poster is blocked). The first S2 build rang only while the epoch was odd (review finding 2).
- **A slot wait that consumes the error CQE** (found while testing review finding 2, `smoke7`). With a
  full ring of aggregated puts, the poster of the signal waits for the CQE of the first put, one ring
  behind, and that CQE is the error: the slot wait keeps the WQE and returns, the signal is posted, and
  its flush then polls a CQE exactly one ring past the CQ's software consumer index. DOCA's windowed
  poll reports "not yet" for that forever, and nobody had reported the error (the slot wait cannot reach
  the classifier): the kernel never exited and the abort did not return, with F4 and with F2 (1 of 1
  each on the intermediate build). Fix: the slot wait records the first error CQE it sees (syndrome,
  vendor syndrome, opcode) in the gate (`swErr`); the poster reports it after its post
  (`tsSwErrReport`, Q4 path `post-slot-wait`, the same once-per-epoch dedupe as a waiter); the
  classifier takes the class from that record when the CQ window holds no root or only trailing flushes
  (the root CQE's slot is reused by the WQE that poster posts next). The helper's round then flips the
  epoch, and the stranded waiter, which checks the epoch every 1024 polls, leaves the window and parks
  (then fails on a decline, or re-maps its ticket after a re-post). The host zeroes the record at publish.
- **Host doorbell.** `gdakiTsRing` writes the 16-bit WQE index into the doorbell's control segment,
  masked (`(pi & 0xffff) << 8`). The first S2 build shifted the whole 64-bit index, so from the 65 536th
  WQE on it spilled into the opmod byte (review finding 3; the NIC ignored it in the measured 1024-thread
  rounds, which rang at indices up to about 200 000).
- **Where each re-posted WQE comes from.** The re-post takes each WQE from its slot, if the 16-bit WQE
  index in the slot's control segment still matches. Otherwise it takes it from the rescue area. Otherwise
  the round declines.
- **Clearing the rescue area.** Entries are counted, and the area is cleared at the next re-post that
  follows any writes, so no entry outlives its epoch.
- **Re-posts larger than the ring go in chunks.**
  - One ring's worth is posted first, then more as the re-posted WQEs complete.
  - The host reads their CQEs; the gate is still closed.
  - Afterwards the host sets the CQ consumer index past the consumed ones.
  - Each direction of the re-post is one copy (S1 used one copy per WQE).
- **Test trigger.** `NCCL_GIN_FAULT_INJECT_AT=wqe:<n>|sig:<n>` fires the hook at a point of the traffic
  instead of at a wall-clock time. Its poll stream and staging are allocated at context creation:
  `cudaFreeHost` inside the hook thread had waited for the kernel and fired the fault only after the
  traffic ended (smoke2).

### C. Symmetric initiation
- **S1:** a REQ that arrived while the helper waited for ACK got NACK, and both sides declined.
- **S2:** the lower rank keeps its round and drops the peer's REQ. The higher rank abandons its own
  round and answers the lower rank's REQ as a responder, reusing its quiesce, Prepare and executed
  counts. Each side re-posts its own unexecuted WQEs from the other's counts. No extra message is needed.
- `NCCL_GIN_TS_TIE_BREAK=0` restores S1.

### D. GID re-lookup on reconnect
- Before every Commit, each rank looks its own GID up again by value, from sysfs: the GID bytes and the
  RoCE type recorded at context creation.
- If the index moved, the new index is set in the context's address handle.
- If the GID is absent, the rank waits for it, bounded by `NCCL_GIN_TS_PATH_WAIT_MS` (default 30 s,
  clamped at start-up to `min(ROUND_MS, HOLD_MS) − HANDSHAKE_MS − 1 s` = 21 s with the defaults, with a
  WARN). The wait runs inside a round: the watchdog surfaces a round older than `ROUND_MS` (25 s) and the
  device threads parked in the gate give up after `HOLD_MS` (30 s), so an unclamped 30 s wait could
  outlive both (review finding 1). Inside a round, the GID wait, the initiator's ACK bound and the
  responder's DONE bound are further cut to what is left of the round minus 0.5 s.
- The initiator's ACK bound and the responder's DONE bound grow by that wait.

### E. PUBLISHING
- **Host:** before the first re-post, it writes PUBLISHING into the epoch half, then reads the word.
  If the device failure bit is set, it declines.
- **Device:** a thread whose second bound expired sets that bit with a CAS, but only if PUBLISHING is
  not set. Otherwise it waits one more bound for the publication, and then fails regardless.

### Review fixes (reviewed build, 2026-10-01)
The independent review of the first S2 build found four items; all are in the final build and diff.

| finding | change | test |
|---|---|---|
| 1 (major): the GID wait (30 s) could outlive the watchdog's round bound (25 s) and the device hold (30 s) | `NCCL_GIN_TS_PATH_WAIT_MS` is clamped at start-up to `min(ROUND_MS, HOLD_MS) − HANDSHAKE_MS − 1 s` (21 s with the defaults) with a WARN; inside a round the GID wait, the initiator's ACK bound and the responder's DONE bound are cut to what is left of the round. The "Flap bounds" limit was corrected | D: 20 s cut transparent 3/3; 30 s cut a clean decline 3/3 at the 21 s bound, no watchdog surface, both aborts returned |
| 2 (minor): the slot wait rang unrung WQEs only while the epoch was odd; a decline writes HOST_FAILED with an even epoch | it rings on odd or HOST_FAILED, and in any case after 16 K spins. Testing this found a second hang (the slot wait consumed the error CQE and the flush was stranded one ring past the CQ window with nothing reported); the slot wait now records the first error CQE in the gate, the poster reports it, and the classifier uses the record (see B) | R: full ring fault-free 5/5; F4 and F2 with a full ring: the kernel exited and the abort returned 5/5 each (hung 1/1 each before) |
| 3 (minor): `gdakiTsRing` wrote the unmasked 64-bit index into the doorbell | `(pi & 0xffff) << 8` | R: `burst_hring2_b`, 16 WQEs rung by the host in 5/5 rounds, transparent |
| 4 (nit): the `tsLateFail` CAS retries | noted under Limits | – |

## Limits
- **Fast-path cost.** The design target of ≤ 1–2% is met at 256 KiB (+1.2%) but not at 4 KiB (+6.0%,
  +0.61 µs). The remaining cost is the two atomics per post and per flush [inferred].
- **The gate's correctness rests on hardware behaviour.** It relies on copy-engine partial writes being
  coherent with L2 atomics. The micro-test exercises this on both GPUs, with no violation in 213 016
  quiesce rounds and 1.1e11 entries. It is not a proof, and other GPU generations were not tested.
- **Bidirectional traffic** could not be tested; see C: on this testbed a sender kernel and a polling
  receiver kernel on the same GPU do not run at the same time (the second one starts when the first
  exits), and the inbound writes of the direction whose receiver is waiting are acknowledged but do not
  land. It is the same on the unpatched build. Symmetric initiation is shown with one-way traffic and a
  test knob that makes the idle rank's helper initiate. In 2 of 30 runs the two rounds did not overlap.
- **Rescue depth.** A re-post can use at most 32 rings of rescued WQEs; beyond that the round declines
  [source]. Colliding rescue entries (two failed WQEs 32 rings apart) also make it decline. The deepest
  case run was 1024 threads: re-posted n up to 721, with 476–593 WQEs taken from the rescue area per
  round.
- **The unrung-WQE ring by the host** was exercised only with the self-report test knob
  (`burst_hring2_b`, 16 WQEs rung by the host in 5 of 5 rounds). Without the knob the helper learns of a
  local fault from a device waiter, i.e. after the poster's next post rang the WQEs, so in the other
  measured rounds (B, `burst_hring_b`) the path was not taken.
- **A poster that over-aggregates** (a whole ring of unrung puts) now waits 16 K spins, about 5 ms on
  the Quadro RTX 5000, before the slot wait rings on its own; stock DOCA would never return there.
- **n = 10 per cell** in the B cells (16…1024 threads and the burst cells), 3 fault-free runs each.
- **The E residual remains**, now only for a helper that stalls for 2 × hold between the PUBLISHING
  mark and the publication. That window holds no firmware command.
- **The late-failure CAS.** `tsLateFail` sets the device failure bit with a compare-and-swap on the gate
  word, which every entry and leave of another thread changes; the loop retries until it wins or sees
  PUBLISHING. Under contention it is not bounded [source]. In the micro-test's CAS-loop run (16 384
  threads) every thread got through; the number of retries was not recorded.
- **Flap bounds.** The address must be back within the path wait (21 s after the clamp) of the round's
  start, which follows the RETRY_EXC detection (about 3.7 s after the cut begins on this testbed): a cut
  of about 24 s is the limit [measured: 20 s survived, 30 s declined; see D]. The first S2 build's text
  ("hold minus detection, about 26 s") was wrong: the 30 s path wait exceeded the watchdog's 25 s round
  bound. The re-lookup handles a changed index of the same address, not a changed address. Only sunny's
  address was cut.
- **Unchanged from S1:** NOP, READ and fetching atomics still make a round decline. A kernel spinning on
  the application's own `waitSignal` is still not released (F2, rank 1).
- **Window size.** On rain, GIN windows above about 50 MiB each failed to register ("ibv_reg_mr_iova2
  ... Bad address"; rain's BAR1 is 256 MiB). The test sizes were chosen to stay below that.
- **Node state.**
  - The leaked `mlx5_1` command slot on rain from 25 Sep is still leaked. The `2ERR_QP` failure count
    stayed at 16 in every hold, and rain had no new mlx5 kernel message (`fwcmd.tar.xz`).
  - Sunny logged one "FWTracer: Events were lost" line on 30 Sep at 23:21:30, outside every S2 hold.

## Provenance and files

| item | md5 (first 8) |
|---|---|
| S2 libnccl, final build (`results/20261001_ts2`: holds `fix1` and everything from 14:12 on) | 0a32b875 |
| S2 libnccl, intermediate builds of 1 Oct: ring condition only (`smoke7`) / plus the slot-wait error record (`prev_6ff74bb6`: the holds of 09:18–12:16, superseded by the final build's re-runs; `lat`, `bmin*`, `stacks` were not re-run, see the text) | 5706dc07 / 6ff74bb6 |
| S2 libnccl, first build (`results/20260930_ts2`) | 744517c9 |
| S1 libnccl / gpudb v2 libnccl | f19cbcfe / 1ed8e0a1 |
| `gin_ts2` against S2, final | d4b1f082 |
| `gin_ts2` against S1 / gpudb / S2 with system-scope gate, final | 8f142f89 / 8025cac0 / fda38dba |
| `gin_ts2` first build, against S2 / S1 / gpudb / system scope | 8fa052cf / c9579b82 / f31e1905 / 432ea4af |
| `gin_bidir_min` against S2 / gpudb, final | b981db00 / 9d4c600d |
| `gate_ce_test`, `two_streams_test` | bd75cc5a, c21fb39a |
| `gin_transparent_s2.diff` (verified: pristine + diff == tree) | 6fc8744e |

| path | what |
|---|---|
| `gin_transparent_s2.diff` | full patch vs v2.32.3-1; `scripts/ts2/make_diff.sh` regenerates it and checks that pristine + patch equals the source tree |
| `gin_ts2.cu`, `gate_ce_test.cu` | the application (modes `none`/`lat`/`F2` as S1, `burst`, `bidir`, `bidir` fused with `GIN_TS_BIDIR_FUSED=1`) and the gate micro-test |
| `gin_bidir_min.cu`, `two_streams_test.cu` | the minimal bidirectional program (modes `both`/`d01`/`d10`/`seq`/`hostrx`/`txonly`/`fused`/`txfirst`) and the two-stream concurrency test |
| `scripts/ts2/build_driver.sh`, `deploy.sh` | build against the S2, S1 or gpudb tree; deploy `~/gi-bundle/gin_ts2/` with md5 and `ldd` checks |
| `scripts/ts2/run_trial.sh`, `batch.sh`, `hold.sh`, `chain.sh`, `gate_test.sh` | one trial, the cells, the holds (each ≤ 15 min through `../common/cluster_run.sh`), the gate test |
| `scripts/ts2/rows.py`, `rows_min.py`, `summarize.py`, `min_table.py`, `tables.sh`, `pack.sh` | logs → CSV → `summary.md`; packing |
| `results/20260930_ts2/`, `results/20261001_ts2/` | `trials_*.csv`, `rounds_*.csv`, `summary.md`, `gate_test.txt`, `hold_*.out`, `gbh_*.txt`, `two_streams*.txt`; per-trial directories stored as `<dir>.tar.xz` (unpack with `for a in *.tar.xz; do tar xJf $a; done` before `tables.sh`) |

Reproduce the first build's tables: `bash scripts/ts2/chain.sh $PWD/results/20260930_ts2 d1 lat e1 b1 b2 b3 c1 fill1`;
the reviewed build's: `bash scripts/ts2/chain.sh $PWD/results/20261001_ts2 lat reg1 reg2 reg3 d2 d3 d4 new1 new2 b4a b4b bmin bmin2 bmin3 bmin4 bmin5 bmin6 bmin7 stacks c4`;
then `bash scripts/ts2/tables.sh results/<dir>`.
