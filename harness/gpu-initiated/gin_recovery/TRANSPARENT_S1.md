# Transparent recovery, step S1: GIN GDAKI, one peer, one QP, one operation in flight

Patch: `gin_transparent_s1.diff`, a full diff against NCCL v2.32.3-1 (12df1a11). It holds, unchanged, the
four layers that `gin_recovery_gpudb.diff` sits on, plus S1 (see "Stack" below). Driver:
`gin_ts1.cu`, an application with no recovery code in it. Scripts: `scripts/ts1/`. Results:
`results/20260925_ts1/`. Design this implements: `../TRANSPARENT_RECOVERY_DESIGN.md` §3, §5, §6, §13
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
  - The second authority agrees: the responder's `next_rcv_psn` matched the executed count in
    105/105 first rounds (65 PSNs per 256 KiB op at PMTU 4096).
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
- **Flag on costs a lot on the fast path [measured].** p50 goes from 10.24 to 16.96 µs at 4 KiB
  (+66%) and from 38.43 to 41.28 µs at 256 KiB (+7.4%). Cost attribution at 4 KiB:
  - system-scope fences instead of GPU-scope: +3.3 µs;
  - the poster gate: +2.6 µs;
  - the counted poll region: +4.7 µs.

  Reducing this is S2 work (see "Next step").
- **Found by the tests [measured].**
  - The fault hook's thread and the helper once issued `2ERR_QP` on the same QP concurrently (1 of
    30 in-flight runs).
    - The firmware command never completed. Kernel log: `2ERR_QP(0x507) No done completion …
      timeout. Will cause a leak of a command resource`, about 104 s later.
    - The waiter's 30 s hold then expired and the flush failed.
  - Fix: every QP state change by the helper is now serialized with the hook (`opMu`, which
    Prepare, Commit and the hook already used). After the fix the cell ran 30/30 with no new kernel
    messages.
  - That one command-resource slot of rain's `mlx5_1` (0000:17:00.1) stays leaked until the mlx5
    driver is reloaded. All later runs were unaffected.


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
  completes. The same code serves the blocking and timeout flush and wait paths. With a timeout,
  time spent held is not charged to the caller.
- **Bounds and giving up.** A held waiter gives up after `NCCL_GIN_TS_HOLD_MS` (30 s) with no new
  epoch. Giving up goes through a commit point with the host (Dekker again):
  - waiter: `atomicMax(abandoned, next)`; fence.sc.sys; read `commit`;
  - host, before anything is re-posted: write `commit = next`, then read `abandoned`.

  Either the host sees the give-up and declines, so nothing is re-posted, or the waiter sees the
  commit and keeps waiting (it fails after one more bound only if the host never publishes). A
  declined QP (`status`) returns `ncclRemoteError` and raises Q4's sticky error, so the blocking
  `flush()`/`wait()` API reports it as in Q4.

### Host (`gin_host_gdaki.cc`): a helper thread inside NCCL

There is one helper thread per GDAKI context of a user devComm, not the application. The Q4
watcher hands it every device-classified error record that belongs to a gated QP. In transparent
mode the watcher does not raise the async error, and `ncclGinGdakiQueryLastError` reports only
declined faults, so a QP that is in ERR while it is being recovered is never reported [source;
measured: 0 async errors in the recovered runs].

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
| 5 | S1 (in `gin_transparent_s1.diff`) | gate, logical tickets, hold-and-rebase waits, helper thread, socket, re-post + host doorbell, `doca_verbs_qp_query_seq` |

- **Checked on the scratch trees:**
  - `gin_transparent_s1.diff` applied to a pristine `git archive v2.32.3-1` reproduces the
    source tree exactly.
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
- **Size of the S1 layer:**
  - 6 files, +1554 / −14 lines including comments.
  - Device: about 270 non-comment lines in 2 headers.
  - Host: about 1000 non-comment lines in `gin_host_gdaki.cc`.
  - DOCA extension (`doca_verbs_qp_query_seq`): about 40 lines.

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
- **Leftovers:** no process was left on either node in any trial except the pre-fix hung trial.
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

The final build (`confirm_lat/`, 3 runs each) is the same: 4 KiB off 10.24 / on 16.96; 256 KiB off
38.40 / on 41.25.

**Cost attribution, 4 KiB p50, 5 interleaved runs each (`lat_attr/`).** The variant builds are
UNSAFE device builds, compiled into the driver only, used here to split the cost and not part of
the patch:

| variant | p50 µs | saves vs flag on |
|---|---|---|
| flag on (reference) | 16.96 | – |
| both Dekker fences at GPU scope (`__threadfence`) | 13.66 | 3.3 |
| poster gate removed | 14.37 | 2.6 |
| poll-region counting removed | 12.29 | 4.7 |
| flag off | 10.24 | 6.7 |

- At 256 KiB the same variants save 0.7–1.9 µs (flag on 41.25; GPU-scope fences 40.51, no gate 39.33,
  no poll counting 40.13), because part of the cost overlaps the transfer.
- The two system-scope SC fences are about half of the overhead [measured]. Why they cost this much
  is [inferred]: the waiter-side fence follows the posted MMIO doorbell write. The rest is also
  [inferred]: the extra `.sys` loads and releases, and the out-of-line calls.
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

A separate reviewer agent read the layer three times (read-only) and then did a final pass.
Every finding was fixed, or is listed under Limits:

| round | findings | fixed |
|---|---|---|
| v1 | 7 major, 6 minor, nits | major: the whole-struct Commit write racing live waiters and parked posters (`cqe_ci` and `active` clobbered); responder quiesce deadlock with traffic in both directions (QPs now go to ERR before the wait); `flushAsync` dropping a failed ticket; device give-up not coordinated with a host re-post; a recovery with one peer clearing another peer's declined error; two contexts on one communicator; use-after-free of the recovery host by the Q4 watcher at teardown. minor: nonmsg never cleared, baseline failure ignored, faults on ungated QPs swallowed, `cudaMemsetAsync` on the helper path, fast-path fences, lbase re-check |
| v2 | 1 new major, 1 major at scale, 2 minor | `tsTicket` retries starving the host's `pollers == 0` read (parking without counter traffic); lost mailbox records (periodic gate scan); check-then-act between give-up and re-post (commit point); the 4-entry lbase ring (logical tickets) |
| v3 | 0 major, 1 minor, nits | parked time charged to the caller's timeout; wording |
| v4 | nothing that is not a documented limit | – |

## What is still not transparent (S1 limits)

- **Declined faults are visible by design.** REM_ACCESS and the other deterministic classes, a
  dead peer, a deadline, a lost mailbox record or a waiter that gave up all end as
  `ncclRemoteError` from the device wait and `ncclRemoteError` from `ncclCommGetAsyncError`.
  - A kernel spinning on the application's own `waitSignal` cannot be released by the library.
  - Measured: the F2 receiver's `ncclCommAbort` did not return while that kernel spun.
- **The stall is visible.** The faulted operation takes 10 ms longer (F1) or 3.6 s (RETRY_EXC).
  An application flush timeout shorter than the detection time still returns `ncclTimeout`, as in
  stock NCCL. Time spent held during a recovery is not charged to the caller.
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
- **Bounds that are not device-side:**
  - A parked poster spins until the helper clears `pause`. The helper's round is bounded, but a
    dead helper thread would leave the poster spinning.
  - After a lost give-up (the host had passed its commit point) a waiter still fails after one more
    hold period.
  - `flushAsync` can block for up to about 2 × hold.
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
  - the doorbell mode per QP (log line);
  - md5 provenance.
- **From source:**
  - DOCA zero-initializes the gate padding;
  - DOCA's device code never touches `reserved1`/`reserved2`;
  - the NIC reads the doorbell record only on doorbell recovery;
  - the host UAR mapping is the one DOCA's CPU proxy rings;
  - one CQE per WQE on the ring CQ.
- **Inferred, not tested:**
  - that the Dekker handshakes hold under contention (the argument is about L2 as the coherence
    point shared by SM atomics, `.sys` loads and copy-engine accesses; the copy engine is outside
    the PTX memory model);
  - that the n = 1 re-post (WRITE executed, ADD not) is correct: it follows from the same rule as
    n = 0 and n = 2 but was not hit;
  - behaviour with more than one op in flight, more than two ranks, symmetric faults, and a peer
    host that dies without FIN (covered only by keepalive/`TCP_USER_TIMEOUT` and the handshake
    deadline).

## Next step: S2 (many operations in flight on one QP)

1. **Cheaper gate.**
   - Put the epoch (high 32 bits) and the poster/poller count (low 32 bits) in one 64-bit gate
     word. Entry becomes one acquire atomic add whose return value carries the epoch: a
     single-location check, so no SC fence is needed. Leave is one release add.
   - The host keeps its copy-engine write of the epoch half and its read of the count.
   - The attribution above says this removes most of the 6.7 µs. Correctness of a copy-engine
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
4. Rounds for several peers without head-of-line blocking; a tie-break for symmetric initiation;
   a host-side classification from the CQ when the mailbox overflows.
5. Reset only the faulted QP pairs, to halve the 3.3 ms Commit, and measure Mode A: re-drive only
   the requester with `sq_psn = next_rcv_psn`.

## Files

| path | what |
|---|---|
| `gin_transparent_s1.diff` | full patch vs v2.32.3-1 (4 earlier layers + S1) |
| `gin_ts1.cu` | the unmodified application driver |
| `scripts/ts1/build_driver.sh`, `deploy.sh`, `make_diff.sh` | build (also `BASE=1` against the gpudb tree), deploy with md5/ldd checks, regenerate the diff |
| `scripts/ts1/run_trial.sh`, `batch.sh`, `lat_batch.sh`, `matrix.sh`, `holdE.sh`, `holdF.sh`, `holdG.sh`, `smoke*.sh` | one trial / one cell / the holds (all inside `../common/cluster_run.sh`) |
| `scripts/ts1/rows.py`, `summarize.py`, `lat_summary.py`, `psn_check.py` | raw logs → CSV → tables |
| `results/20260925_ts1/` | `runs/` (main matrix + in-flight cell), `confirm/` + `confirm_lat/` (final build), `lat/`, `lat_attr/`, `f1g0_before_opmu_fix/` (the hang), `smoke*/`, `trials*.csv`, `rounds*.csv`, `summary.md`, hold outputs. Each per-trial directory is stored as `<dir>.tar.xz` (55 MB of logs, mostly repeated warning lines, pack to 1.6 MB; the archives round-trip byte for byte). Run `for a in *.tar.xz; do tar xJf $a; done` in that directory before re-running the scripts below |

Scratch (not in the repo): tree `$SCR/agent_ts1/nccl-src` (git: pristine → 4 layers → S1 working
changes); build `$SCR/agent_ts1/build`; variants `$SCR/agent_ts1/var/`. Bundle
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
```

