# NVSHMEM IBGDA transparent recovery (T1)

Patch: `nvshmem_ibgda_transparent.diff`, a full diff on the same base as `nvshmem_ibgda_ft_v2.diff`
(NVSHMEM `7bb2e99c` + `../nvshmem/nvshmem_ibgda_fault_inject.diff` +
`../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff`); it contains FT v2.2 unchanged except where T1
hooks in. Switch: `NVSHMEM_IBGDA_FT_TRANSPARENT=1` (needs `NVSHMEM_IBGDA_FT=1`,
`NVSHMEM_IBGDA_FT_RING_CQ=1` and the GPU NIC handler; every PE must set it). Unset, the library
behaves as v2.2.

With the switch on, a QP error on an RC connection is repaired inside NVSHMEM while the
application's kernel keeps running. The application (`nvshmem_t1.cu`) has no recovery code. PE 0 runs
one kernel that loops `nvshmem_putmem_signal_nbi` (signal ADD 1) + `nvshmem_quiet`. PE 1 runs one
kernel that loops `nvshmem_signal_wait_until` and checks each slot on the GPU. The hosts check
everything at the end. Recovered classes: LOCAL_QP_ERR, and RETRY_EXC while the peer's library socket
is alive. Every other class is declined, with a bounded error to the application.

## Results (final build)

Cluster: rain (PE 0, Quadro RTX 5000, `mlx5_1`) and sunny (PE 1, RTX A4000, `mlx5_0`), RoCE v2, IB
timeout 14, retry count 7, one RC QP per peer. Every number is counted from the raw logs by
`scripts/t1/rows_t1.py` and `summarize_t1.py`; times are median [min–max]; sets are directories under
`results/20260930_t1/`. Earlier builds, the external review and the latency bisect: `summary_t1.md`.

**Transparent**: both processes exited 0, PE 0 ran every iteration with `nvshmemx_ibgda_ft_status`
(observation only) never set, every slot bit-exact on PE 1's GPU and host, the final signal exact
(each ADD once), host error view and device status clean on both PEs. **Declined**: a DECLINE line,
PE 0's kernel and `nvshmem_finalize` returned. Else **failed**; **void**: PE 0 never started (setup).

Faults: **F1** the library's hook moves PE 0's QP to ERR (LOCAL_QP_ERR); **F3** PE 1's QP (PE 0 gets
RETRY_EXC, peer alive); **F2A** the application's own bug, a put past the heap (REM_ACCESS); **F4**
SIGKILL of PE 1 (RETRY_EXC, FIN); **FLAP** sunny's RoCE address removed and re-added; **SOCK** an outage
of the library's socket only. Fault time random in 0.9–1.9 s unless stated.

### Regression (set `reg_final2`)

| cell | workload | n | transparent | declined | failed | recovery rounds | WQEBBs re-posted per round |
|---|---|--:|--:|--:|--:|--:|---|
| no fault | 160 × 256 KiB, 15 ms gap | 10 | **9** | 0 | 0 (1 void) | 0 | – |
| F1 | same | 20 | **20** | 0 | 0 | 20 | 2 (put + ADD) in 20/20 |
| F1 in flight | 16000 × 4 KiB, no gap, fault 70–250 ms | 20 | **20** | 0 | 0 | 20 | **0 in 10** (the responder had executed put and ADD), 2 in 10 |
| F3 | 420 × 256 KiB | 5 | **5** | 0 | 0 | 5 | 2 in 5/5 |
| F1 × 5, 3rd shot inside the commit | 260 × 256 KiB | 5 | **5** | 0 | 0 | 25 | 2 in 25/25; the in-commit shot hit the re-post 5/5 |
| F1, 4 CTAs × 8 threads on one QP | 100 × bursts of 16 × 1 KiB per thread, 51200 slots | 10 | **10** | 0 | 0 | 10 | > 2 in 10/10 |
| F2A app bug, REM_ACCESS | 100 × 256 KiB | 10 | 0 | **10** | 0 | 0 | – |
| F4 SIGKILL | 400 × 256 KiB | 5 | 0 | **5** | 0 | 0 | – |

The void trial is an ssh connection reset at the launch of PE 1, before `nvshmem_init`. [measured]

- **Exactly once.** In 10 of the 20 in-flight rounds the responder had executed the put and the ADD
  before PE 0 saw their completions; its `rmsn` put the executed prefix at the end of the ring, nothing
  was re-posted, the signal ended exact (the `prefix` control fails in exactly those rounds). [measured]
- **Declines are bounded.** PE 0's kernel returned with the status set and `nvshmem_finalize` returned
  (F2A 20.8 ms [max 21.2], F4 24.6 [max 24.9]); record to DECLINE 0.17–0.65 ms. PE 1's
  `signal_wait_until` is application memory, not a library wait, so it ran to the driver's timeout.
  Recovered classes: LOCAL_QP_ERR (F1, 65/65), RETRY_EXC (F3 5/5, flap 18/18); declined: REM_ACCESS
  10/10 (syndrome 0x88), RETRY_EXC with FIN 5/5. [measured]
- **Round time** (initiator): F1 4.64 ms [4.18–5.46] (quiesce 0.10, prepare 0.12, handshake 2.54,
  commit 0.82, finish 0.03; the DCI reset, ~0.4 ms, runs before the handshake); in flight 4.41; F1 × 5
  4.47 [3.58–53.0] (one round of 125 took 53 ms, host scheduling); mt 6.69 (quiesce 2.4 ms: 32
  posters stop); F3 5.71. F3's 3.6 s slow operation is the NIC's retry timeout, not the recovery.

### Address flap (a real path fault; sets `flap_final2`, `flap_cut25`, `flap_v22`, `flap_nogid`)

`../../nccl-integration/stage2/gid_blackhole.sh` adds a secondary address to both RoCE ports (the RC QPs
run on those GIDs) and removes sunny's for `cut` seconds 1.5 s into a 1000 × 64 KiB run (20 ms gap).
After every hold both ports had only their primary address; sunny's nvme error-line count stayed 0.

| build | cut | n | transparent | declined | failed | RETRY_EXC after the cut start (s) | slowest operation (s) | recovery round (ms) | sunny GID index moved |
|---|---|--:|--:|--:|--:|---|---|---|---|
| v2.2 (FT on, no recovery) | 0.5 / 6 / 15 s | 2 / 2 / 2 | 0 | 0 | **6** | 3.80–4.05 | – | – | 6/6 |
| **T1 final** | 0.5 s | 5 | **5** | 0 | 0 | 3.91 [3.90–3.96] | 3.65 [3.63–3.71] | 8.04 [6.05–8.32] | 5/5 |
| **T1 final** | 6 s | 5 | **5** | 0 | 0 | 3.86 [3.81–3.95] | 6.02 [6.01–6.04] | 2427 [2377–2477] | 5/5 |
| **T1 final** | 15 s | 5 | **5** | 0 | 0 | 3.99 [3.80–4.05] | 15.05 [15.02–15.06] | 11342 [11290–11494] | 5/5 |
| T1, final transport (`flap_cut25`) | 25 s | 3 | **3** | 0 | 0 | 3.84 [3.84–3.97] | 25.04 [25.03–25.07] | 21464 [21364–21465] | 3/3 |
| T1 without the GID re-lookup (control) | 6 s | 3 | 0 | **3** | 0 | 3.94 [3.83–4.02] | – | – | 3/3 |

The GID index moves on every re-add (72/72 cuts over all flap sets) and DEVX QPs keep the old
source-GID index, so even a 0.5 s cut is permanent for the QP: under v2.2 RETRY_EXC fires ~3.9 s after
the cut (6/6), the application gets the error and `nvshmem_finalize` did not return within 65 s. T1
recovers with RETRY_EXC and a live peer: sunny's helper finds its GID by value at the new index at
once (0.5 s) or after 2.4, 11.3 or 21.4 s (6, 15, 25 s cuts), PE 0's device threads hold that long,
and the application sees one slow operation of about max(retry timeout, cut) and no error. Without the
re-lookup (control) RTR fails with the stale index and the round declines 5–17 ms after the record.

### Library-socket outage (set `review4`)

PE 0's T1 socket port is dropped by iptables in both directions for 8 s, 1.5 s into a 1000 × 64 KiB
run (20 ms gap); no RDMA fault in `sock`, F1 at 12 s in `sock1`.

| cell | n | transparent | declined | failed | socket lost (PE 0 / PE 1) | errno | back (PE 0 / PE 1) | cut start → back (s) | F1 rounds after it |
|---|--:|--:|--:|--:|---|---|---|---|---|
| SOCK (no fault) | 5 | **5** | 0 | 0 | 5/5 | ETIMEDOUT ×5 | 5/5 | 3.52 [3.51–3.53] | – |
| SOCK then F1 at 12 s | 5 | **5** | 0 | 0 | 5/5 | ETIMEDOUT ×5 | 5/5 | 3.52 [3.51–3.53] | 5/5 recovered, 10.1 ms [9.9–10.7] |

Both sides classify the loss as a lost path, not the peer's death; PE 0 re-dials sunny's listener (a
new port, outside the rule), PE 1 re-accepts, the application saw no error, 0 rules were left. [measured]

### A fetching atomic in flight (`--fetch`; sets `fetch_fixed`, `review4`)

PE 0's loop adds `nvshmem_long_atomic_fetch_add(ctr, 1, 1)` after the put+signal of every K-th
iteration and records the value (expected: the number of fetches before it); PE 1 reports the counter.
A fetch in the unfinished range [C, R) when the round starts has an ambiguous local result, so the
round declines and the fetch returns the poison value (all bits 1, v2.2's rule).

| cell | workload | n | transparent | declined | failed | decline names the fetch | poison from the failed iteration on, none before | stale | PE 1 counter = exact fetches |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| F1, no gap, fetch every iteration | 16000 × 4 KiB, fault 70–250 ms | 12 | 0 | **12** | 0 | 12/12 | 12/12 | 0 | 12/12 |
| F3, fetch every iteration | 1000 × 4 KiB, 20 ms gap | 10 | 0 | **10** | 0 | 10/10 | 10/10 | 0 | 10/10 |
| F1, 15 ms gap, fetch every 8th iteration | 160 × 256 KiB, 20 fetches | 12 | **11** | 1 | 0 | 1/1 | 1/1 | 0 | 12/12 |
| no fault, fetch every 8th iteration | 160 × 256 KiB | 3 | **3** | 0 | 0 | – | – | 0 | 3/3 |

Decline reason: `QP 0x..: WQE opcode 0x12 at N cannot be re-posted (fetch, READ or DUMP in the
unfinished range)`, 0.64 ms [max 0.73] after the record; `nvshmem_finalize` 19–27 ms. A completed fetch
does not decline and stays exactly once (11/12 recovered, all 20 values exact; in the 12th the next
iteration fetched). With a fetch every iteration a fault between operations declines too: an idle QP's
error surfaces on the next post, which fetches. [measured]

### Negative controls (one resync step removed by a knob; F1; sets `neg`, `neg2`, `flap_nogid`)

Run on the b2/b3 builds; the resync steps are unchanged since.

| knob | what is skipped | n | transparent | declined | failed | how it fails |
|---|---|--:|--:|--:|--:|---|
| `ring` | host doorbell after the re-post | 5 | 0 | 0 | **5** | both kernels hang (signal stuck at 93–128 of 160) |
| `ringci` (v2 knob) | ring-CQ counter resync | 5 | 0 | 0 | **5** | both kernels hang |
| `rotate` | send-ring rotation (U to slot 0) | 5 | 0 | **5** | 0 | the NIC executes stale slots: LOC_LEN, declined |
| `prefix` | executed prefix (re-post from the completed index) | 25 | 11 | 0 | **14** | signal 16001/16000 (ADD twice), signal ahead of data; fails in every round with Uexec = C + 2, passes with Uexec = C |
| `remap` | waiters' ticket remap (60 × 2 MiB, no gap) | 10 | 2 | 0 | **8** | quiet returns early, the next iteration overwrites the source: 1 slot bad |
| `gid` | GID re-lookup by value (6 s address cut) | 3 | 0 | **3** | 0 | RTR with the stale source-GID index fails, declined |

### DCI reset under a full GPU (sets `review`, `review2`, `review3`; a limit)

F1 while a second application kernel occupies every remaining SM thread slot (191 CTAs of 256 threads
next to the loop kernel's CTA; `review`/`review2` with one CTA pending): **0/24 recovered, 24/24
declined** at the hold bound, bounded (`nvshmem_finalize` 29.4 ms [max 29.9]). The DCI reset is not the
cause (75/75 F1 rounds of the regression reset the DCI, no kernel): the helper's 64-byte `cudaMemcpyAsync`
stops completing while every slot is taken, fault or not (5.6 s with no fault, 83.6 s with F1,
`dci_diag`/`dci_diag2`), so no round starts. See Limits. [measured]

### Gate micro-test (`tests_t1/gate_race_test.cu`)

The host flips the epoch with 4-byte copies while every device thread enters and leaves with 64-bit
atomics: 0 torn values in 327.7 M + 102.4 M atomics per run, PASS in every run (rain sm_75 in 5 holds,
sunny sm_86 in 1). Enter + leave costs 380 ns (rain), 376–414 ns (sunny); S1's Dekker gate 2239–2395 ns.

### Fault-free latency (set `lat_final2`)

Put + signal + quiet, one thread, 2000 operations × 5 reps × 5 runs per cell, interleaved, GPU
`%globaltimer`; runs are bimodal (12.4 vs 14.1 µs for v2.2), so the best run stands next to the median
of all 25 reps. "FT on, ring" is the v2.2 FT configuration T1 needs, T1 off.

| size, stat (µs) | v2.2, FT off | T1 build, FT off | T1 build, FT on (ring), T1 off | T1 on |
|---|--:|--:|--:|--:|
| 4 KiB p50, best run | 12.384 | 13.056 | 13.440 | **14.240** |
| 4 KiB p50 / p99, median of all reps | 12.672 / 14.368 | 13.088 / 14.272 | 13.440 / 14.368 | 16.256 (4 of 5 runs slow) / 16.416 |
| 256 KiB p50, best run | 40.256 | 40.768 | 40.960 | **41.760** |
| 256 KiB p50 / p99, median of all reps | 40.352 / 40.992 | 40.768 / 41.248 | 40.960 / 42.176 | 41.888 / 43.008 |

T1 on costs +1.86 µs at 4 KiB and +1.50 µs at 256 KiB against v2.2 with FT off (+0.80 against the
same build with FT and ring CQs on). With the switch off the T1 build costs +0.67 and +0.51 µs; the
bisect of that cost is under Limits. [measured]

## How it works

Same structure as S1 (`../gin_recovery/TRANSPARENT_S1.md`, "How it works"): a pause gate for posters,
waits that hold across a recovery with logical tickets, a helper thread inside the library that runs
the round over its own TCP socket, the executed prefix from the responder's `rmsn`, a host re-post with
a host doorbell, a commit-point give-up handshake, a watchdog and a teardown hook. What differs for
NVSHMEM:

**Device (`ibgda_device.cuh`).**
- **Gate** (64 B per RC QP in GPU memory). S1's gate used two words and system-scope SC fences on both
  sides (Dekker; most of its +6 µs). T1 puts the epoch (high 32 bits, written by the host with a 4-byte
  copy) and the count of device threads inside (low 32 bits) into one 64-bit word: a poster enters with
  one `atomicAdd` whose return value carries the epoch (one location: host write and entries ordered at
  L2, no fence) and leaves with one `red.release.gpu.add`; `gate_race_test.cu` tests the no-tearing assumption.
- **Posters are counted from reserve to submit** (`ibgda_reserve_wqe_slots` .. `ibgda_submit_requests`;
  in warp paths one thread reserves and another submits); one that finds the epoch odd backs out before
  it reserves. Where a post can wait for a recovery (slot wait, in-order ready CAS) the poster leaves the
  count, waits for the next stable epoch, enters again (its WQEs are in the ring and move with it), then
  shifts its reservation by delta (below) and rewrites its WQEs' index fields. The host proceeds at count 0.
- **Waiters are not counted.** Quiet, fence and fetch waits read the ring CQ and write CQ state
  (`cons_idx`, the ring counter); indices only grow across a recovery (next point), so a stale
  `atomicMax(cons_idx)` is a no-op, and the ring counter carries the epoch's low 24 bits in bits 40..63
  so that a stale CAS fails. A waiter takes its ticket (epoch, `off`, `ready_head`) in one stable epoch,
  validates completions against it, re-maps it after a recovery (L = D − `off`), and enters the count
  only to record an error CQE.
- **Indices jump instead of restarting.** After `2RST` the NIC's WQE counter restarts at 0; S1 restarted
  the device indices too. T1 moves every index to B, the next multiple of 65536 above every old index,
  and rotates the send ring so that the first unexecuted WQE U sits in slot 0 (= index B): the NIC
  counter equals D mod 65536 again, post and poll code is unchanged, `off` grows by B − U per recovery.
- **WQEBBs vs messages.** `rmsn` counts messages, device indices 64-B WQEBBs, and NVSHMEM posts
  multi-WQEBB WQEs (the barrier's signal: a 2-WQEBB masked atomic plus a NOP). Each post adds its surplus
  to the gate's `xbb` when its range is ready; a host walk of [C, R) turns the executed count into an index.
- **Flag off.** Each hook tests one flag word of the `__constant__` device state and branches around
  the T1 path; the rare paths (hold, give-up, index fix, error record) are out of line. The build knob
  `NVSHMEMI_IBGDA_T1_DEVICE` (bit 0 post hooks, bit 1 wait hooks, bit 2 the rest; 0 = v2.2's device
  code, the switch refused at init) exists for the latency study.

**Host (`ibgda.cpp`).** The round is S1's (quiesce, drain, executed counts, REQ/ACK, 2RST, commit
point, rebase, INIT/RTR/RTS, re-post, publish, DONE) with these differences:
- **One helper thread per process**, fed by the v2.2 mailbox watcher (the application sees no record
  of a gated QP), which also runs the watchdog; an `atexit` hook stops and joins it when a process
  exits without `nvshmem_finalize`. The lower PE initiates; a higher PE that sees a fault sends NOTIFY.
- **What may be re-posted** is read from the ring: the host walks [C, R) and accepts RDMA WRITE, NOPs
  and atomics whose local address is the internal buffer's slot 0 (non-fetching); a fetching atomic,
  READ or DUMP there declines (its local result is ambiguous even if the responder executed it). The
  executed prefix comes from the responder's `rmsn` (QUERY_QP with its QP in ERR), so an ADD the
  responder executed is not re-posted.
- **Commit point.** Nothing device-visible is written before it. A device wait that reaches `HOLD_MS`
  records "abandoned" and fences; the host writes "commit", fences and reads "abandoned": either the host
  declines or the device keeps waiting (S1's handshake, per gate). After it the host publishes `off` and
  `xbb` before the re-post doorbell (a poster leaving its hold with FAILED then shifts), the epoch last.
- **Bounds.** `ROUND_MS` (watchdog, before the commit point) has the floor quiesce + drain + handshake
  + 2 × GID wait + 5 s (73 s); `HOLD_MS` (one bound before the commit point, one after; the hold starts
  at the device record, before a socket re-dial, a NOTIFY → REQ wait or another peer's round, since
  rounds serialize per process) the floor max(`ROUND_MS` + 3 × handshake, 2 × handshake + GID wait) +
  5 s (93 s). Every device-state copy of the helper is a `cudaStreamQuery` poll bounded by `COPY_MS`
  (2 s, less when the round's budget ends sooner); a copy that does not complete declines the round,
  and `rc_endpoint_lock` is held only around DEVX commands, never across a copy.
- **GID re-lookup**: before INIT/RTR each side looks its local GID up again by value (and RoCE version)
  and waits up to `GID_WAIT_MS` for the address; the initiator's ACK bound covers that wait.
- **No kernel launches** on the recovery path: CQ refill, doorbell record and ring rewrite are host
  copies (a memset kernel would wait behind the application's persistent kernel). The local DCIs, which
  the fault hook also moves to ERR, are reset before the commit point the same way, never fatally for
  the RC round (a DCI with a post in flight stays in ERR and is retried from the idle scan).
- **One lock for every DEVX command** (`rc_endpoint_lock`, also taken by the fault hook): rain's
  `mlx5_1` has a leaked command slot.
- **Policy**: LOCAL_QP_ERR recover; RETRY_EXC recover unless the peer's library socket shows FIN; every
  other class declines. Only a clean FIN is the peer's death: a socket that dies with an error (RST,
  keepalive, `TCP_USER_TIMEOUT`) is a lost management path, closed before Linux's following
  `recv() == 0` could look like a FIN and re-dialed by the lower PE every 0.5 s (the higher PE accepts
  on its listener every loop, so a re-dial it has not yet noticed is taken up); a fault while the path
  is down waits one handshake bound and then declines as "OOB path down", never as death (Stage 2's
  rule). Decline: a host-mapped mirror word per gate is set first (a plain store the held device waits
  read over PCIe, so the decline reaches them even when copies to the gate stall), then QPs to ERR,
  gate FAILED (waits return, later posts go to the parked QP), FAIL to the peer, host error record
  (`nvshmemt_ibgda_ft_query`), device status (`nvshmemx_ibgda_ft_status`), transport marked failed so
  that `nvshmem_finalize` skips device collectives. The helper is joined with a bound at teardown and
  `atexit` (detached with a warning otherwise).

## Limits

- **Tested scope.** 2 PEs, 1 RC QP per peer, one NIC per node, RoCE v2; PE 0 initiates, PE 1 only
  receives apart from NVSHMEM's own barriers. More than two PEs, several RC QPs per peer and DCIs
  (not gated) were not tested. Apart from FLAP and SOCK the faults come from the library's hook (QP
  to ERR) or the application's own bug (F2A), not from a broken link.
- **A GPU with every SM thread slot taken stops the helper.** Its device-state reads and writes are
  `cudaMemcpyAsync` + `cudaStreamSynchronize` on its own stream, and with the application occupying
  every thread slot a 64-byte copy did not complete until the application's kernels ended (`dci_fill`,
  24/24 declined at the hold bound). A standalone program with the same filler copies in microseconds
  (`tests_t1/fill_copy_test.cu`, set `fill_copy`): the stall is specific to the NVSHMEM process, cause not
  identified. Reaching the device state without a CUDA stream (a BAR1 mapping) would remove it; not done.
- **Flag off costs +0.5–0.7 µs per operation** (4 KiB 13.06 vs 12.38; 256 KiB 40.77 vs 40.26). The
  bisect (set `bisect`, seven interleaved cells, `summary_t1.md`) puts it in the device hooks: with
  every hook compiled out the T1 source runs at v2.2's latency, the host libraries cost ≤ 0.13 µs, post
  hooks alone +0.6, wait hooks alone +0.35, both +0.5 (not additive). Registers, spills and the flag
  word's cache line are unchanged; the remaining explanation, not verified at SASS level, is that each
  hook's branch stops the compiler from overlapping the global loads around it. Only the build knob
  removes it; a run-time switch would need a per-operation dispatch at the API layer.
- **Refused setups.** T1 stays off, with a warning, with more than 8 RC QPs to one peer, without
  ring CQs, park or the GPU NIC handler, or with v2 bounds mode; every PE must set the switch (a PE
  without it hangs in the init allgather).
- **Declined, by design.** A fetching atomic, READ, `g`/`get` or DUMP in [C, R): accepting those in
  [C, U_exec) would hand the application a poison value with a clean status; accepting those whose
  success CQE already sits in the CQ before the error CQE (a definite local result) is feasible and
  not done. Also every class but LOCAL_QP_ERR / RETRY_EXC; a peer whose socket shows FIN; a fault
  while the management path is down (after one handshake bound) or whose round is in progress when it
  drops (at the ACK or DONE bound); a device-state copy that does not complete within `COPY_MS`.
- **Bounds.** A device wait holds for at most `HOLD_MS` (78 s), then gives up through the commit-point
  handshake and the round declines; the watchdog declines a round longer than `ROUND_MS` (73 s) before
  its commit point; the address must be back within `GID_WAIT_MS` (30 s). Held device threads spin.
- **Not handled.** An application wait on its own memory (PE 1's `signal_wait_until`) is not released
  by a decline (the library's waits are); a peer that comes back with another address (the GID
  re-lookup is by value, local only); the transport's device-wide GID index is not updated.
- **Open items from the review.** A second device give-up in the same round is not handshaken; QPs
  created after init can push the count past 8; a DCI post between the quiescence check and the DCI's
  2RST is not excluded; the `atexit` join is not tested.
- **Kernel log.** rain's `mlx5_1` (one leaked firmware command slot since 2026-09-25) logged no new
  mlx5 message; its NVRM BAR1 messages fall into void trials with a 400 MiB heap and the other agent's
  holds. sunny logged `FWTracer: Events were lost` at 09-30 23:21:30 (F2A trials), 10-01 02:27:47 (no
  T1 hold) and 12:18:23 (`dci_diag`), as on 09-25; no nvme error lines.

## Provenance

| sets | date (KST) | driver | transport | host lib | build |
|---|---|---|---|---|---|
| reg_final2, lat_final2, flap_final2 | 10-01 10:36–11:11 | `f40cf527` | `c69d6cc4` | `0dcfb0e1` | **final**: `nvshmem_ibgda_transparent.diff` |
| review3, review4 (dci_fill, sock, sock1, F3 fetch) | 11:25–12:05 | `7a166d01` (exact-fit SM filler) | `c69d6cc4` | `0dcfb0e1` | final libraries |
| reg_fixed, review, flap_fixed, fetch_fixed, flap_cut25 | 08:48–09:58 | `1489d29a` | `c69d6cc4` | `d4692937` | final transport; device hooks placed differently (see `summary_t1.md`) |
| flap_v22 | 09-30 23:26–23:33 | `d90585c8` | `6913dea6` | `54a9d23a` | v2.2 (`~/gi-bundle/nvshmem_ft2`) |
| neg, neg2, flap_nogid | 09-30 23:11 – 10-01 01:13 | `ef3e996a`, `83402302`, `aabbcf80` | `446e82f6`, `c28f555e` | `f8158c55`, `d8883a20` | b2/b3 builds (negative controls) |

md5 prefixes are from the trials' `.meta` files; the transport builds bit-identically, host library and
driver do not. `scripts/t1/make_diff_t1.sh` regenerates the diff and checks that it re-applies on the
base and reproduces the tree, which rebuilds to transport `c69d6cc4`. Earlier builds: `summary_t1.md`.

## Files

- `nvshmem_ibgda_transparent.diff`: the patch; T1 code in `ibgda_device.cuh` (block after
  `ibgda_ft_ring_poll`, hooks in reserve/submit/quiet), `nvshmem_common_ibgda.h` (gate, flag),
  `ibgda.cpp` ("T1 (research)" .. "end T1"). `nvshmem_t1.cu`: the application, no recovery code
  (`--fetch`, `--fetch-every`, `--fill-sms`, `--bad-at` shape the workload). `tests_t1/`: the gate
  race test and the copies-under-a-full-GPU test.
- `scripts/t1/`: build/run (`build_driver_t1.sh`, `deploy_t1.sh`, `deploy_variants_t1.sh`, `env_t1.sh`,
  `run_trial_t1.sh`, `run_matrix_t1.sh`), holds through `../common/cluster_run.sh` (`holds.sh`,
  `hold_final.sh`, `hold_review*.sh`, `hold_generic.sh`, `flap_hold.sh`, `specs/`), analysis (`rows_t1.py`,
  `summarize_t1.py`, `tables_t1.sh`, `sass_size_t1.sh`, `summary_history.md`), `make_diff_t1.sh`, `pack_t1.sh`.
- `results/20260930_t1/`: `summary_t1.md` (every generated table and the history), `trials_t1.csv`,
  `rounds_t1.csv`, `trials_bisect.csv`, `bisect_runs.txt`, `hold_*.out`, one `<set>.tar.xz` per set
  (raw logs, `.meta` files, dmesg snapshots, leftover checks).

Reproduce (on rain): `BASE=v22 scripts/t1/build_driver_t1.sh; scripts/t1/build_driver_t1.sh;
scripts/t1/deploy_t1.sh; scripts/t1/hold_final.sh reg|lat|flap` (other cells: `holds.sh`,
`hold_review4.sh`); `scripts/t1/tables_t1.sh` after unpacking the sets rebuilds the CSVs and the summary.
