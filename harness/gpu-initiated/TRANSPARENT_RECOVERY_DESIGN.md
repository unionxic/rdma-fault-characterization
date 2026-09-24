# In-library, app-transparent, multi-op recovery for GPU-initiated RDMA

Target stacks: **(1) NVSHMEM IBGDA** (GPU NIC handler) and **(2) NCCL GIN GDAKI** (DOCA GPUNetIO),
on the rain/sunny ConnectX-6 (VPI, MT28908, fw 20.43.4100) RoCE v2 testbed, PeerMappingOverride=1
on both nodes (GPU-rung doorbells), IB ack timeout 14. This document specifies how to move fault
handling **inside the library** (transport + device code), so a fault is recovered with no change
to the application's kernels or its control flow, for the realistic case of **many QPs and many
WQEs in flight** — the two objections the reviewer raised against
`gin_recovery/RECOVERY_DESIGN.md` and `nvshmem_ft/DESIGN.md`:

- (a) both were validated with 1 QP, 2 PEs, one operation in flight, so they decline in a
  DeepEP-like workload (tens of QPs, hundreds of WQEs);
- (b) neither is transparent: the kernel must end on an error, the app calls `ft_status`, runs the
  OOB handshake, reads the receiver's signal, and relaunches from the failed iteration; and the
  resident sentinel occupies a GPU thread and forbids `cudaDeviceSynchronize`.

This design keeps the exactly-once machinery of the two prior designs (parse the SQ into PSN
ranges, read the responder's expected PSN, bilateral reset with fresh PSNs, resync the device
indices, replay only the missing work) and adds the three things that make it transparent and
multi-op: a **device-side pause gate** in the post path so producers stop without the kernel
ending; **device waits that block across a recovery** (using the abort-flag / ticket the libraries
already have) so the kernel never sees an error; and a **per-QP, per-peer** recovery epoch so the
whole QP fan-out is handled at once. Sibling to the CPU path `nccl-integration/stage2/DESIGN_stage2.md`.

Tags: **[source]** read in the code named; **[measured]** measured in this repo's prior runs (cited
dir); **[probe]** measured by `transparent_probe/` (this task; small n, stated per result); **[inferred]** reasoned from
the two, not directly tested.

---

## 0. Summary of the feasibility answers

1. **Exactly-once without app knowledge is a PSN problem, and the PSN is readable.** The
   requester's WQEs map deterministically to PSN ranges (WRITE/READ consume `ceil(bytes/MTU)`
   PSNs, atomics 1 PSN); the responder's `next_rcv_psn` (mlx5 QPC, read by DEVX `QUERY_QP`) names
   the first PSN it has not executed, so the library knows the exact executed prefix without the
   app telling it anything. **[probe]** The responder's `next_rcv_psn`, and its `rmsn`, equalled the
   executed prefix found in responder memory in **28/28** data points (10 with the responder QP in
   ERR, 18 in RTS). READs were confirmed to count `ceil(bytes/MTU)` PSNs. In the one trial where the
   requester's completions trailed the responder by 11 executed requests and a partly received
   multi-packet WRITE, replay from the PSN boundary was exactly-once. **Limit:** only 1 trial had a
   non-empty replay and none with the responder in ERR mid-burst. The exactly-once claim at scale
   still needs the N ≥ 30 run of §10 (§11.1).
2. **Producers can be quiesced without ending the kernel.** Both libraries already funnel every
   post through a per-QP lock/CAS (`post_send_lock` / `sq_lock`, `ready_head` CAS). A pause flag
   checked in the reserve path, plus an "active posters" count, lets the host stop all producers on
   a QP with a bounded wait and a Dekker-style fence, at the cost of one relaxed load per post on
   the fast path (§3).
3. **Device waits can block across a recovery instead of returning an error.** The GDAKI wait
   already loops on `poll_one_cq_at(qp, ticket)` and only returns on a *good* completion (it spins
   on `-EIO`), and it honours an `abortFlag`/timeout [source]. If the recovery rebases the device
   indices so `ticket` still maps to the replayed completion, the *same* wait loop returns success.
   The app's kernel source is unchanged; the library's inlined poll gains one subtraction (item 4),
   so apps must be recompiled (§12). NVSHMEM's `ibgda_poll_cq` also needs to spin and yield on an
   error CQE instead of asserting.
4. **Pre-fault tickets survive the QP reset only through a per-QP base offset.** After `2RST` the NIC
   restarts its send WQE counter at 0 [measured: gin_recovery, nvshmem_ft]. It also ignores the WQE
   ctrl-segment index field and reports its own counter in the CQE [probe Q4, n=1, fresh QP]. So the
   library keeps the logical indices waiters hold, restarts only the physical slot and the NIC
   counter, and has every device poll subtract a per-QP `base` written under pause. It also advances
   the CQ mapping (`cqe_rsvd`) cumulatively, so stale ring entries are never taken for new ones
   [measured, gin_recovery negative controls]. §6.3 has the full inventory.
4a. **Rewinding the requester alone into executed requests is safe only in a shallow window**
   [probe Q3, n=1 per depth]. Duplicates were absorbed silently when the requester rewound up to 16
   requests. At 64 and 200 the requester timed out with RETRY_EXC. No atomic was ever applied twice,
   so the failure is safe but still a decline. Mode A therefore resumes at the responder's PSN
   boundary rather than the requester's last ACK, and re-issuing an executed-but-unacked fetching
   atomic is allowed only within that window.
5. **Multi-QP is handled by a recovery epoch per (context, peer).** All QPs of a peer are reset
   and replayed together; healthy QPs to other peers keep running. The declines that remain are
   the deterministic classes (REM_ACCESS, REM_INV_REQ, LOC_*) and a dead peer — the same set as
   the CPU path.

The biggest residual risks and the recommended first step are in §12–§13.

---

## 1. Contract (both stacks)

- **Flag off** (`NVSHMEM_IBGDA_FT` / `NCCL_GIN_FAULT_RECOVERY` unset): byte-for-byte the stock
  library. The device reads one extra `__constant__`/`__ldg` pointer per poll and one relaxed flag
  per reserve; the host creates no thread and no buffer. This is the same no-measurable-overhead
  footprint the prior designs already demonstrated (+1% at 4 KiB, `nvshmem_ft` `lat/`) [measured].
- **Flag on:**
  - **Transparent success.** For a recoverable fault the kernel that issued the operations neither
    returns an error nor is relaunched: its `put`/`atomic`/`wait`/`quiet`/`flush` calls complete
    exactly as if the fault had not happened, with every WRITE landed once, every non-fetching
    atomic applied exactly once, every fetching atomic's result delivered exactly once, and every
    READ's data correct. The app's control flow is unchanged.
  - **Bounded, never-worse-than-stock.** Every wait in the recovery path has a deadline; on any
    precondition failure or unrecoverable class the library **declines** — the QPs stay in ERR and
    teardown returns, exactly as the prior designs measured. A declined fault is the *only* case
    the app can observe, through a status query it may ignore (§9).
  - **Correctness or failure, never silent loss/dup.** A recovery either restores exactly-once or
    declines; it never completes an operation whose data did not arrive and never double-applies a
    non-idempotent one.
- The library provides the **mechanism**; unlike the prior designs it also provides the **policy
  inputs that only the transport can see now that they are inside it**: kernel quiescence (via the
  device pause gate, not an app contract), the peer's liveness (OOB socket owned by the transport's
  bootstrap), the receiver's signal delta (read by the library from the QPC PSN, not from the app),
  and which operations to replay (from the SQ ring + PSN, not from an app checkpoint).

---

## 2. What "transparent" costs, and why the prior designs were not

The prior designs surfaced the error to the kernel because they had no way to (i) stop the GPU
producers without the kernel exiting and (ii) resume a device wait after a reset. This design adds
both, so the app is untouched. The table contrasts them:

| step | prior (`gin_recovery`, `nvshmem_ft`) | this design |
|---|---|---|
| detect | device wait returns error → kernel returns | device wait **blocks** (spins with yield / abort-flag) while the host recovers (§5) |
| quiesce producers | app must stop launching kernels; library checks QP indices | host sets a **device pause gate**; in-kernel posters drain and park (§3) |
| who reads the signal delta | the app reads the receiver's signal and passes it in | the library reads the responder `next_rcv_psn` via `QUERY_QP` (§4, §11) |
| who replays | the app relaunches from the failed iteration | the host **or** the device replays the missing WQEs; the kernel is not relaunched (§6) |
| resident cost | a sentinel warp + no `cudaDeviceSynchronize` | no sentinel needed for detection when the wait blocks; classification is in the wait loop |
| API the app still sees | `ft_status`, OOB handshake, checkpoint/restart | one optional async-error query for **declined** faults only (§9) |

---

## 3. Quiescing GPU producers without ending the kernel

The reset in §6 rewrites the producer indices the device reads, so every thread that is posting on
a QP under recovery must be stopped first, and no new post may start, **while the kernel keeps
running**. Both libraries already serialise the critical part of a post, which is the hook point.

### 3.1 What the post path already does [source]

NVSHMEM `ibgda_submit_requests` → `ibgda_post_send` (`ibgda_device.cuh:1561`):
```
reserve:  wqe_idx = atomicAdd(&mvars->tx_wq.resv_head, num_wqes); wait_for_slot_availability(...)
ready:    while (atomicCAS(&ready_head, base, base+n) != base);   // strict order
submit:   ibgda_lock_acquire(&mvars->post_send_lock);             // atomicCAS(lock,0,1)
          old = atomicMax(&tx_wq.prod_idx, new);
          if (new>old){ update_dbr(); ring_db(); }                // GPU handler writes the record + UAR
          ibgda_lock_release(&mvars->post_send_lock);
```
GDAKI `doca_gpu_dev_verbs_reserve_wq_slots` → `..._submit_db` (`doca_gpunetio_dev_verbs_qp.cuh:114,524`):
```
reserve:  wqe_idx = atomic_add(&qp->sq_rsvd_index, count); wait_until_slot_available(...)
ready:    mark_wqes_ready: atomicCAS(&sq_ready_index, from, to+1) loop
submit:   lock(&qp->sq_lock); old=atomic_max(&sq_wqe_pi,pi); if(old<pi){ ring_db; update_dbr; ring_db; } unlock
```

### 3.2 The pause gate

Add three device words per QP, in the 24 reserved padding bytes NVSHMEM already carries in
`nvshmemi_ibgda_device_qp_management_t` (`char padding[24]`) [source] and in the two reserved
regions of `doca_gpu_dev_verbs_qp` (`reserved1[8]`, `reserved2[64]`) [source] — so **no struct
size changes** (the prior FT patches used the same padding and kept the static_asserts):

- `pause` (u32): 0 = run, 1 = draining. Host sets it.
- `active` (u32): count of threads inside the post critical section.
- `epoch` (u32): incremented by the host at each recovery; the device stamps each WQE's logical
  region with it (§4) so a straggler from before the reset is ignored.

**Reserve-time gate** (one relaxed load on the fast path):
```
// front of reserve_wqe_slots / reserve_wq_slots, before the atomicAdd
if (ld_relaxed(&pause)) {                     // slow path only when a recovery is pending
    while (ld_acquire(&pause)) nanosleep();   // park; do not consume a WQE slot
}
atomicAdd_system(&active, 1);                 // enter
fence_release_sys();
... reserve, build, mark-ready, submit ...
fence_release_sys();
atomicAdd_system(&active, -1);                // leave
```

**Host quiesce** (in `prepare`, per QP):
```
st_release_sys(&pause, 1);                    // 1) stop new entrants
membar;                                       // 2) Dekker: our store precedes our load of active
while (ld_acquire_sys(&active) != 0) { poll deadline }   // 3) wait for in-flight posters to leave
// now no thread is between reserve and submit on this QP
```

**Correctness (Dekker across PCIe).** A poster does `store(active=+1); fence; if(load(pause)) back
out`. The host does `store(pause=1); fence; load(active)`. With a full system-scope fence on both
sides, at least one of the two sees the other's store, so it is impossible for a poster to pass the
gate *and* be uncounted while the host reads `active==0`: if the host reads `active==0`, every
poster that had incremented has also decremented, and any poster still to come reads `pause==1` and
parks. The membar on the device is `__threadfence_system()` (NVSHMEM `IBGDA_MEMBAR` when
`nic_buf_on_gpumem` is false [source]) / `fence_release<SYS>` (DOCA) [source]; on the host it is a
release store to mapped memory followed by an `mfence` before the acquire load. The pause word and
`active` live in host-pinned mapped memory (like the prior mailbox) so the host store is visible to
the GPU and vice versa.

**Fast-path cost.** One relaxed load of `pause` (predicted not-taken) and one system-scope
`atomicAdd(active,±1)` per posting group. The `atomicAdd` is the only real add; it can be avoided
entirely by reusing the existing lock: the host can instead *acquire every QP's `post_send_lock` /
`sq_lock` from the host side* (they are plain 32-bit words in mapped/GPU memory) after setting
`pause`, which blocks new submits without a per-post counter — but acquiring a GPU-memory lock from
the host is only safe under PeerMappingOverride and needs the same fence discipline, and it does not
stop a thread that is between `reserve` and `submit`. The `active` counter is therefore the robust
choice; measured fast-path cost target ≤ 1% (same budget the classifier already meets) [inferred;
to be measured as in `nvshmem_ft/lat/`].

**Parking vs. slot consumption.** The gate parks a thread *before* `atomicAdd(resv_head)`, so a
paused thread holds no WQE slot and the reserved/ready/prod indices are quiescent and equal when
`active==0` — which is exactly the precondition the reset needs (§6) and which the host also
verifies from the indices (`resv_head==ready_head==prod_idx`, `sq_rsvd==sq_ready==sq_wqe_pi`), as
the prior designs already do [source, measured].

### 3.3 Waiters keep running

A thread that is only *waiting* (`quiet`, `wait`, `flush`, a signal spin) is not a producer and
must not be parked — it is what §5 keeps alive across the recovery. The gate is only in the
reserve/submit path.

---

## 4. Mapping WQEs to PSNs, and reading the executed prefix

### 4.1 SQ ring → PSN ranges [source + probe]

The library walks the SQ ring from the last known consumer index to the producer index and, for
each WQE, reads the ctrl segment (opcode, `ds`) and the operation segment:

- **RDMA WRITE / WRITE-with-imm / SEND**: one WQE, `ceil(byte_count / PMTU)` PSNs (the NIC
  segments the message into PMTU packets, each its own PSN). `byte_count` is in the data segment;
  inline writes carry the length in the inline header. A put ≤ `IBGDA_MAX_TRANSFER_SIZE` (1 GiB) is
  a single WQE [source `ibgda_write_rdma_write_wqe`, `ibgda_cal_transfer_size`,
  `doca..._wqe_prepare_write`].
- **ATOMIC (FETCH_ADD / masked FA / CAS)**: exactly **1** PSN. DeepEP's signal is a 4-byte masked
  FETCH_ADD (`MLX5_OPCODE_ATOMIC_MASKED_FA`) [source DeepEP `ibgda_write_amo_add_wqe`]; NVSHMEM /
  GIN signal is `SIGNAL_OP_ADD` = ATOMIC FA [source]. This is the non-idempotent case (§7).
- **RDMA READ**: consumes `ceil(byte_count / PMTU)` PSNs of the requester's outbound sequence
  (the read *responses* carry those PSNs), even though the requester emits one request packet;
  after a read the responder's `next_rcv_psn` advances by that many. GIN `get` and the MCST/CST
  flush are reads [source `getImpl`, `ibgda_cst` uses a DUMP]. **[probe]** confirms the read
  packet-count accounting against the responder PSN.

The library therefore builds, per QP, a table `(logical WQE index → first PSN, packet count,
opcode)` — the same table it needs to replay (§6). PSNs are 24-bit; the table is kept modulo 2^24
relative to the connect-time `psn0`.

### 4.2 Responder's expected PSN [source + probe]

The responder's mlx5 QPC has `next_rcv_psn[0x18]` (the PSN it will next accept from the requester)
and `rmsn[0x18]` (responder message sequence number); both are returned by DEVX `QUERY_QP`
[source `nrc_prm.h`; the prior `nrc_devx.c` already reads `hw_sq_wqebb_counter`, `next_send_psn`,
`last_acked_psn` this way]. Because RC executes requests in order, the executed prefix is exactly
the requests whose entire PSN range is `< next_rcv_psn`; the first unexecuted request is the one
whose first PSN `== next_rcv_psn` (or the first `>=` it). The library computes the replay set from
this alone — **no app checkpoint, no receiver-signal read by the app**.

Two facts must hold on hardware, and are what the probe measures (§11):

- **Q1** After the responder QP has gone to ERR, does `QUERY_QP.next_rcv_psn` still equal the PSN
  after the last request the responder actually executed (ground truth: responder memory)? And in
  the RETRY_EXC case where only the *requester* errs and the responder stays RTS, does it? Prior
  work already saw `QUERY_QP` return a coherent `hw_sq_wqebb_counter` in ERR and coherent
  `next_send_psn`/`last_acked_psn` [measured, nrc_devx / nvshmem_ft `QUERY_QP` 222/222 in ERR], so
  the read itself is reliable; Q1 is specifically about `next_rcv_psn` on the *responder* matching
  memory to the packet. **Answer [probe]: yes in 28/28 data points (§11.1), and `rmsn` equals the
  executed request count too.**
- **Q4** Does the NIC take the WQE ctrl-segment index field or its own WQE counter as authoritative,
  and which one does the send CQE's `wqe_counter` report? **Answer [probe, n=1, fresh QP]: its own
  counter.** WQEs with index fields 1000–1003 in slots 0–3 executed and completed with `wqe_counter`
  0–3. With the counter restarting at 0 after `2RST` [measured, prior], logical indices cannot be
  carried into the CQE, so device polls need the per-QP base of §6.3. Not yet checked: the same test
  *after* a `2RST` (expected to behave the same, since the counter is the NIC's own).

### 4.3 Idempotence classes for replay [source]

- **WRITE / WRITE-with-imm**: idempotent — replaying to the same address with the same bytes is
  safe while the receiver has not consumed the buffer (lockstep and DeepEP both keep the buffer
  reserved until the op is confirmed). Replay any WRITE whose PSN ≥ `next_rcv_psn`.
- **Non-fetching atomic (signal ADD)**: **not** idempotent. Replay it **only if** its PSN ≥
  `next_rcv_psn` (i.e. the responder never executed it). If it was executed-but-unacked (its PSN <
  `next_rcv_psn` but the requester's completion was an error), it must **not** be re-sent — this is
  precisely why reading `next_rcv_psn` (not the requester's completion count) is the authority.
- **Fetching atomic (fetch-add, CAS, and RDMA READ result)**: the *result* is lost if the op was
  executed-but-unacked. Two options: (i) **decline** the recovery if any executed-but-unacked
  fetching op is in the gap (safe, simple); (ii) **re-issue** it, which is exactly-once at the
  responder only if the responder answers a duplicate from its atomic/read replay state rather than
  executing it again. **Q3 [probe, n=1 per depth]:** duplicates were absorbed with correct
  completions and no double-applied atomic at rewind depths 4 and 16. At depths 64 and 200 the
  responder did not answer and the requester ended in RETRY_EXC; still no counter exceeded 1. I infer
  the window is the responder's read/atomic resources (`max_rd_atomic`); that is not measured. The
  design uses (i) by default. It enables (ii) only when the executed-but-unacked gap holds at most as
  many reads/atomics as that limit, which the probe showed is at least 3 atomics plus reads in 16
  requests. Beyond the window the failure is a safe RETRY_EXC, which is then declined.

---

## 5. Device waits that block across a recovery (so the app's kernel source needs no change)

### 5.1 GDAKI [source]

`waitImplCore` / `flushImplModeCore` (`gin_gdaki.h:337,393`) loop:
```
while (true) {
  status = doca_gpu_dev_verbs_poll_one_cq_at(qp, ticket);   // ticket = sq_rsvd_index-1
  if (status == 0) return success;                          // ONLY good completions exit
  if (HasTimeout && clock64()-start >= timeout) return ncclTimeout;
  if (testAbort(abortFlag, steps)) return success/abort;
}
```
On an error CQE `poll_one_cq_at` returns `-EIO`, which is neither 0 nor a timeout, so the loop
**keeps spinning** — this is why a GDAKI kernel hangs on a fault today [measured, RESULTS.md]. That
same property is what makes transparency possible: **if the recovery makes the completion for
`ticket` appear at the right place, the loop returns success on its own.** The recovery must:

**preserve the logical ticket numbering.** The waiter holds `ticket = sq_rsvd_index-1` in a
register, so the host cannot rewrite it. Therefore the reset keeps the *logical* producer numbering
(`sq_rsvd_index` / `resv_head` are **not** reset to 0) and restarts only the *physical* WQE slot and
the NIC WQE counter at 0, with the CQ mapping (`cqe_rsvd` for the ring CQ; the single slot for the
collapsed CQ) arranged so the replayed op the waiter is blocked on completes at the ticket the
waiter already holds. This is the collapsed-vs-ring subtlety of §6.3 and the reason `cqe_rsvd` must
advance cumulatively [measured, gin_recovery negative control]. Probe **Q4** shows the CQE carries
the NIC's own 0-based counter, not the index field. So the poll's `wqe_counter` comparison (live on
sm < 90, which covers both GPUs here) must subtract the per-QP base of §6.3. That is a one-line
change in the library's inlined poll; the app's kernel source does not change.

The `abortFlag`/timeout path is a fallback only: flipping the library's abort word makes the waiter
return "not done", which is transparent only if the app loops on the result — app-specific — so the
**preferred path is the blocking one above: the waiter never returns until the real completion
lands.**

The bound: the waiter blocks for at most `drain + handshake + commit + replay` (≈ 3–8 ms after
detection in the prior measurements [measured]) plus the detection time itself (≈ 3.6 s for
RETRY_EXC at timeout 14). NVSHMEM's and GDAKI's device polls have **no** timeout by default
(`NVSHMEM_TIMEOUT_DEVICE_POLLING` is off [source]; GDAKI's `HasTimeout` is only set when the app
passes a timeout), so blocking across a recovery is the stock behaviour already — nothing to
change there.

### 5.2 NVSHMEM [source]

`ibgda_poll_cq` (`ibgda_device.cuh:501`) loops on `wqe_counter` and, on an error CQE, sets
`status=-1` then hits `assert(status==0)` — compiled out in release, so `nvshmem_quiet` returns
"success" over a flush [measured]. The FT patch already reads the CQE opcode in the loop to
classify. To block-across-recovery instead of returning, the loop is changed to: on an error CQE,
**do not** advance `cons_idx`, spin-with-`nanosleep` while `epoch` is unchanged, and re-read the
slot after the recovery refills it (the refilled slot carries the replayed op's completion at the
same `cons_idx`). Because NVSHMEM's CQ is **collapsed** (every CQE in slot 0), the waiter is waiting
for `wqe_counter == prod_idx-1`; after the reset the replayed op's completion writes slot 0 with the
new `wqe_counter`, and the waiter proceeds. The waiter must therefore also have its target
(`prod_idx` snapshot) rebased, which §6.3 handles by keeping the logical producer numbering.

### 5.3 What the app API must still expose

Only for **declined** faults. The device wait returns an error only when the library gives up
(unrecoverable class, dead peer, deadline). For that path the app needs a way to learn the comm is
dead so it can tear down — the prior `nvshmemx_ibgda_ft_status(pe)` / `ncclCommGetAsyncError`
suffices and may be ignored by an app that is willing to crash on an unrecoverable fault. No
positive-path API. `nvshmem_quiet` still returns `void`; a recovered fault is invisible to it.

---

## 6. Bilateral reset, replay, and keeping device indices valid

### 6.1 Which QPs, and the recovery epoch

A fault is scoped to a **(context, peer)** pair. All **RC** QPs of that peer in that context are
reset and replayed together (DeepEP uses `num_rc_per_pe` = tens of RC QPs per peer, GIN uses
`ginContextCount` = 17–129 exclusive contexts [source]); QPs to other peers keep running. Both ends
of each pair are reset together in Mode B (each end's new receive PSN is the other's new send PSN),
or only the requester is reset in **Mode A** (§6.2). The epoch counter (§3.2) is bumped so
in-flight device state from before the reset is fenced off.

**DCIs.** NVSHMEM's DC path uses shared DCIs (one initiator QP fans out to many DCTs) with no fixed
peer, so a DCI in ERR is reset **locally** with its stock DCI attributes and its in-flight requests
replayed from the DCI's own SQ — the responder side is a DCT (stateless target) and needs no reset;
the PSN authority is the per-DCT `next_rcv_psn` the initiator learns over OOB. The prior
`nvshmem_ft` already resets local DCIs not in RTS at commit [source]. DeepEP and GIN GDAKI here use
RC (`num_rc_per_pe`, GDAKI RC QPs), so DC is a secondary path; a DCI whose target set spans peers
that are not all quiescible is declined. When a single logical message is striped across several
QPs (DeepEP splits a large put over QPs), the epoch must cover every QP of the message atomically
(§6.1 already resets all of a peer's QPs together); a message whose per-QP PSN prefixes cannot be
reconciled into one message boundary is declined (§12).

### 6.2 Mode A (one-sided) vs Mode B (bilateral)

- **Mode B — responder was in ERR** (LOCAL_QP_ERR on the requester with a peer QP also down, or a
  responder-initiated ERR). Reset both ends, pick fresh PSNs, replay from `next_rcv_psn`. This is
  the prior designs' path, generalised to N ops via §4.
- **Mode A — responder still RTS** (the common RETRY_EXC / path-flap case, and the local WR_FLUSH
  case where only the requester's QP left RTS). The responder's QP is **untouched**; the library
  resets only the requester and brings it back up with `sq_psn = responder.next_rcv_psn` (read over
  OOB), then replays from that PSN. The responder sees an uninterrupted PSN stream and never changes
  state — maximally transparent, and it halves the firmware cost (one side's INIT/RTR/RTS instead of
  two). **[probe]** validates Mode A exactly-once with hundreds of ops in flight. Mode A is only
  legal when the responder is provably in RTS at the requester's-expected PSN (checked via
  `QUERY_QP` over OOB); otherwise fall back to Mode B.

### 6.3 Device-visible state across the reset [source + measured]

After `2RST` the NIC restarts the send WQE counter at 0 and expects WQE 0 in slot 0 [measured]. The
CQ object is **not** reset; its producer keeps counting. Every device word that encodes a WQE index
or a doorbell must be made consistent — the two prior designs enumerated this exhaustively and
proved the two non-obvious items by negative control; the multi-op design reuses that inventory
with the index rows changed for ticket preservation (§5, Q4):

| state (NVSHMEM / GDAKI) | on recovery | why |
|---|---|---|
| per-QP `base` (new) | = logical index of the first replayed WQE (E), written under pause before RTS | physical slot, ctrl index, doorbell value and CQE `wqe_counter` are all `logical − base` (Q4: the CQE carries the NIC's own counter, restarted at 0) |
| `resv_head` / `sq_rsvd_index` | **kept** (logical) = E + #replayed after the host replay | blocked waiters hold logical tickets; the next reservation continues the logical sequence |
| `ready_head` / `sq_ready_index` | kept, set equal to `resv_head` | the submit CAS compares against it; quiescent at pause |
| `prod_idx` / `sq_wqe_pi` | kept (logical); only the value rung = `(prod − base) & 0xffff` | logical indices only grow, so `atomicMax` keeps working. (The prior designs reset indices to 0 and had to zero this word: a stale value suppressed every doorbell [measured]; that hazard remains if anyone resets to 0.) |
| `cons_idx` / `cqe_ci` | set to E (every request < E is executed and done) | a smaller value makes waiters for executed-but-unacked ops wait forever; a larger one releases waiters early (silent success) |
| `get_head`/`get_tail` (NVSHMEM), `last_issued/visible_get` (GIN) | cleared | fetch tickets in WQE index space |
| `post_send_lock` / `sq_lock` | 0 | quiescent, no holder |
| CQ mapping `cqe_rsvd` (GDAKI) | old + S cumulatively | ring poll reads WQE j at CQ pos j+`cqe_rsvd`; must advance by the epoch's WQE count, **not** be set to it (measured: non-cumulative → polled a stale CQE, timed out) [measured] |
| doorbell record (send word) | 0 while in RESET | NIC may reload it; stale → fetches stale WQEs |
| CQ buffer | not rewritten (ring, GDAKI) / refilled 0xff (collapsed, NVSHMEM) | ring: stale entries have wrong owner parity; collapsed: slot 0 still holds the old error CQE, must be refilled after 2RST (measured) |
| Q4 sticky error / async result | cleared | else later waits keep failing |

**Ticket preservation (the multi-op addition).** In the prior single-op designs the WQE index space
restarted at 0 and every pre-fault ticket was declared void — which is exactly the app-visible break
this design removes. To keep blocked waiters (§5) valid, the logical producer numbering
(`sq_rsvd_index` / `resv_head` and the waiter's `ticket`) is **kept**, while the *physical* WQE slot
and the NIC WQE counter restart at 0; the CQ mapping (`cqe_rsvd` for the ring CQ; the collapsed CQ's
single slot for NVSHMEM) is set so that the replayed op which the waiter is blocked on completes at
the ticket the waiter holds. This is the one genuinely new correctness obligation over the prior
designs.

**Q4 settles how.** The NIC ignores the ctrl-segment index field and reports its own WQE counter in
the CQE [probe, n=1, fresh QP]. That counter restarts at 0 after `2RST` [measured, prior]. So after a
reset the CQE can never carry a preserved logical index. Every device poll that compares the CQE's
`wqe_counter` with a logical ticket must therefore subtract a **per-QP base**:
`base[qp]` = the logical index at which the current NIC incarnation began. The host writes it under
pause, before RTS.

- GDAKI ring poll: on sm < 90 it requires `wqe_counter == cons_index & 0xffff` [source, cq.cuh];
  with the base it becomes `wqe_counter == (cons_index - base) & 0xffff`. The CQ slot mapping stays
  `cqe_rsvd`, advanced cumulatively. Our GPUs are sm_75 and sm_86, so this check is live here. On
  sm ≥ 90 DOCA checks only the owner bit, and the slot mapping carries the whole burden.
- NVSHMEM collapsed poll: it derives `cons_idx` from `wqe_counter` and the high bits of `idx`
  [source, ibgda_poll_cq]. It must add `base` back. The same applies to the WQE slot computation and
  the doorbell value in the post path, which already sit behind the pause gate.
- The base is a coherent load (`ld.relaxed`/volatile, not `__ldg`/`loadConst`) read in the same
  poll iteration as the CQE. A waiter that read the old base against a new-epoch CQE must retry. A
  per-QP `epoch` read before and after the CQE, seqlock style, detects this.

This is a small change to **library device code** (one subtraction per poll and per slot
computation) and no change to **app source**. Because the device API is header-inlined, apps must
still be **recompiled** against the new headers (§12).

### 6.4 Replay: by host or by device

- **By host** (default, matches the prior designs): under pause, the host copies/patches the ctrl
  segments of the unexecuted WQEs into the (reset) SQ starting at physical slot 0, writes the
  doorbell record, and rings the UAR from the host mapped `bf`/`sq_db` pointer. Bounded, simple,
  and it needs no cooperation from the running kernel. Cost ≈ the prior designs' commit (0.5–1.5 ms
  for INIT/RTR/RTS + a memcpy per WQE) [measured].
- **By device**: the host only rebases the indices and clears the pause flag; the parked producer
  threads, on unpark, re-post the unexecuted WQEs themselves (they still hold the op descriptors in
  registers/shared memory only if they had not yet returned — generally they have, so device replay
  needs the descriptors persisted). Device replay avoids host WQE copies but requires the library to
  have persisted each op's descriptor; deferred to a later stage.

---

## 7. Replay semantics and exactly-once (N ops)

Let the executed prefix (from `next_rcv_psn`, §4.2) be the requests with PSN `< P = next_rcv_psn`.

1. **No old-incarnation op executes after P is read.** In Mode B both QP ends are in ERR/RESET
   before `P` is read; in Mode A the responder stays RTS but the requester is reset to `sq_psn=P`,
   so it emits nothing below `P`. A stale packet hits the fresh expected PSN with probability 2^-24
   [inferred, as prior].
2. **WRITEs** with PSN ≥ P are replayed (idempotent). WRITEs with PSN < P are done.
3. **Non-fetching atomics** with PSN ≥ P are replayed exactly once; those < P are done and not
   re-sent (this is the exactly-once guarantee for the DeepEP signal-add pattern with many signals
   in flight: each signal maps to one atomic WQE with one PSN, and the boundary `P` splits them
   cleanly).
4. **Fetching atomics / READs** with PSN < P whose result the requester did not receive: **decline**
   by default; re-issue only within the measured duplicate-absorb window (§11 Q3).
5. A replay that faults again starts a new epoch and re-reads `P`; an op executed during a failed
   replay is counted, not repeated.

This is the prior designs' §7 with the single-op `d ∈ {0,1}` generalised to `d ∈ [0, N]` and the
op-type split done per WQE from the PSN table rather than from a single known signal.

---

## 8. OOB channel, liveness, and the helper thread [source, prior]

The transport's bootstrap already owns a TCP socket per peer on the management network (NVSHMEM's
unique-id socket; NCCL's `bootstrap`/`base.sock`). The recovery uses it for the REQ/ACK/DONE
handshake and for liveness, exactly as `stage2/DESIGN_stage2.md` §5/§7: `recv(MSG_PEEK|DONTWAIT)`
== 0 → FIN (peer dead), ECONNRESET/EPIPE/ETIMEDOUT → dead, EAGAIN → no evidence; RETRY_EXC is
recovered only on "no evidence" and the handshake itself is the second liveness proof. `SO_KEEPALIVE`
+ `TCP_USER_TIMEOUT` bound a silent peer death. A **helper thread** per process (one, not per QP)
polls all peer sockets and steps any (context,peer) with input or a recovery in progress, using
trylock so it never blocks a progress path — same structure as the CPU Stage 2 helper. This is a
transport-internal thread, not the app's; it replaces the app-run handshake of the prior designs.

---

## 9. Decline paths and teardown [measured, prior]

Unrecoverable classes (REM_ACCESS 10/0x88, REM_INV_REQ 9/0x8a, LOC_*, RNR_RETRY_EXC, an
executed-but-unacked fetching atomic outside the safe window, a dead peer, a deadline, too many
epochs) → decline: QPs stay in ERR, the device wait returns an error (the one app-visible path,
§5.3), and teardown returns (the FT patches already make `nvshmem_finalize` / `ncclCommAbort` return
after an error by skipping the device barrier and the bootstrap barrier) [measured: finalize
returned 17–29 ms, incl. dead peer]. The app tears the comm down; this is the same "never worse than
stock" guarantee.

---

## 10. Overhead and staged plan

**Fast-path overhead (flag on, no fault):** one relaxed `pause` load + one system atomic per posting
group (§3), plus the existing in-loop CQE read (measured +1% at 4 KiB, +0.25% at 256 KiB in
`nvshmem_ft`). Target ≤ 1–2%; measured as in `nvshmem_ft/lat/` with 4 KiB / 256 KiB and, new here,
with a **burst of many ops** and **tens of QPs**.

**Stages:**

1. **S0 — probe (this task).** `transparent_probe/`: Q1 (responder `next_rcv_psn` vs memory, ERR
   and RTS), Q2 (Mode A/B exactly-once, N≈256 ops), Q3 (duplicate-atomic window), Q4 (WQE index
   field after reset). N≥30 per cell. Decides Mode A legality and the fetching-atomic policy.
2. **S1 — device pause gate + block-across-recovery, single QP, single op.** Prove the kernel is
   not relaunched (the app just calls `put;quiet` in a loop; a fault mid-loop is invisible). Reuse
   the prior host prepare/commit. N≥30.
3. **S2 — multi-op on one QP.** Burst of 128–512 ops then `quiet`; inject mid-burst; verify
   exactly-once from the PSN table. N≥30. This is the direct answer to objection (a).
4. **S3 — multi-QP / multi-peer.** `num_rc_per_pe`/`ginContextCount` > 1; fault on one QP; others
   keep running; recovery epoch per (context,peer). N≥30.
5. **S4 — Mode A one-sided** (responder untouched), the transparency win; and device-side replay
   (S5, optional).

**Test plan** mirrors `stage2/DESIGN_stage2.md` §11: flag-off == stock (T0), single inject not on a
boundary (T1), **many ops in flight** (T2: 512 ops, inject at a random op), multi-QP (T3), repeated
injects (T5), symmetric (T6), GID blackhole / path flap → RETRY_EXC → Mode A (T7), SIGKILL → clean
decline (T8), mute peer → deadline decline (T9), latency (T10), fast-path overhead with a burst and
many QPs (T11). Every run verifies every op's data bit-exact and every signal/counter exactly once
on both ranks. "Many ops in flight" is driven by posting a large burst with all-but-last unsignaled
(NVSHMEM `nbi` puts / GIN `AggregateRequests`) and a single `quiet`/`flush`, then injecting during
the burst.

---

## 11. Probe (`transparent_probe/`): design and results

`tr_probe.c` (CPU only, mlx5 DEVX, one RC QP pair, requester=rain/mlx5_1, responder=sunny/mlx5_0)
builds the four question tests with WQE shapes matching the libraries (RDMA WRITE one SGE of sizes
64 B to 7·MTU, 8-byte ATOMIC FETCH_ADD to a distinct counter per atomic, RDMA READ), a 64-byte **ring** CQ,
every WQE signaled, the SQ doorbell record's **send** word written (the correct word, avoiding the
CPU-proxy bug of `nvshmem_rootcause/`). A deterministic plan of N mixed requests is shared with the
responder over the OOB socket so the responder can compute ground truth from its own memory
(every WRITE's bytes vs the pattern, every FETCH_ADD counter) and report `next_rcv_psn`/`rmsn` from
`QUERY_QP`. Scenarios: `resp_err` (responder → ERR mid-burst; requester ends in RETRY_EXC; Mode B),
`req_err` (requester → local ERR; responder stays RTS; Mode A), `dup` (no fault; requester alone
resets and rewinds its PSN into already-executed requests — the atomic-duplicate window), `wqeidx`
(ctrl index field ≠ physical slot after reset). Run only through `common/cluster_run.sh`; each
process self-bounds (`alarm`). Build: `make` here and (via `run_probe.sh`) on sunny.

The core question — **does the responder's `QUERY_QP.next_rcv_psn` equal the executed prefix, in
ERR and in RTS** — is what `Q1_MATCH` in the output reports (`prefix_from_psn == mem_prefix`);
exactly-once after recovery is `EXACTLY_ONCE` (every write landed, every atomic counter exactly 1,
every read verified); the atomic-duplicate window is `fadd_multi` vs rewind depth.

### 11.1 Results

Two cluster runs, each one hold under `common/cluster_run.sh` (logs:
`transparent_probe/results/run1`, `.../run2`). psn0 = 0x100 for seed 1. Every figure below is
**[probe]**. Where I infer something from it, the text says so.

**run1 was invalid for exactly-once.** It exposed two probe bugs: (i) inline WRITEs were built with
`ds=0`, a malformed WQE, so every trial's requester failed deterministically at its first inline WRITE
(executed prefixes 0/0/0/1/3, the same for both scenarios with the same seed); (ii) the replay poll
consumed stale flush CQEs of the failed burst because the probe had no **CQ drain**. The drain bug is
itself a finding: without the drain step of §4/§6 (consume one CQE per posted WQE before reusing the
CQ), the replay's completions cannot be told from the failed burst's flushes. Both are fixed (inline
WRITEs replaced by small plain WRITEs, which does not change PSN accounting; `drain_cq()` added).
run1 still gives 14 valid **Q1** data points (its 4 `dup` trials print Q1 before aborting), because
Q1 is measured on the responder before any replay: `Q1_MATCH` 14/14 at prefixes 0–3, five of them
with the responder QP in ERR.

**run2 (corrected binary, 15 trials):**

| scenario | n | responder state at QUERY_QP | executed prefix (PSN = memory) | Q1_MATCH | rmsn = prefix | requests replayed | exactly-once | host recovery time |
|---|--:|---|---|---|---|---|---|---|
| `resp_err` (Mode B) | 5 | ERR | 256 in 5/5 (the burst finished before the responder's 2ERR took effect) | 5/5 | 5/5 | 0 | 5/5 (trivial: nothing to replay) | 1.30–1.37 ms |
| `req_err` (Mode A) | 5 | RTS | 256 in 4/5; **234 in 1/5** (ra_s4) | 5/5 | 5/5 | 0 ×4; **22** ×1 | 5/5 | 0.59–0.62 ms |
| `dup` with 46 READs in the plan | 4 | RTS | 256 | 4/4 | 4/4 | (Q3, below) | – | – |

- **Q1 holds in every data point: 28/28** (run1 14, run2 14). `QUERY_QP.next_rcv_psn` gave exactly
  the prefix found in responder memory, and `rmsn` equalled the executed request count in every run2
  trial. That covers the responder QP in ERR (10 points, all at prefixes 0–3 or 256) and in RTS
  (18 points, one mid-burst). The query took 60–84 µs.
- **The READ accounting is confirmed.** With 46 READs of 256 B / 8 KiB / 4·MTU+7 B in the plan,
  `next_rcv_psn` = 0x373 = psn0 + 627. That sum is only right if each READ counts
  `ceil(bytes/MTU)` PSNs; counting 1 PSN per READ would give a different value. The same plan was run
  4 times, so this is one plan confirmed repeatedly, not four independent plans.
- **The executed-but-unacked case, one trial (ra_s4).** The requester had 223 successful
  completions, but the responder had executed 234 requests (`next_rcv_psn` 0x372, `rmsn` 234, and
  memory agrees). A replay driven by requester completions would have re-sent 11 executed requests,
  some of them atomics. Request 234, a multi-packet WRITE, was partly received: `next_rcv_psn` was
  3 packets into it and memory showed one partial write. Mode A reset only the requester, restarted it
  at request 234's boundary PSN 0x36f, and replayed 22 requests. The responder absorbed the 3
  duplicate packets. Final state: 205/205 WRITEs landed, 51/51 counters exactly 1, 0 partial writes.
  This is the design's Mode A path end to end, but it is **one** trial.
- **Coverage gap.** Only 1 of 15 run2 trials had a non-empty replay. There are **zero** valid
  Mode B trials with a non-empty replay (run1's were invalidated by its bugs), and none with the
  responder in ERR mid-burst. The fault landed after the 256-request burst had finished (≈0.4–0.6 ms)
  in 9 of 10 trials. The next run must inject earlier (before or right at the doorbell), or use a
  longer burst, and must reach N ≥ 30 per cell.
- **Q3, duplicate absorption, by rewind depth.** One trial per depth. The requester alone was
  reset and rewound into already-executed requests; the plan included READs.

  | rewind depth (requests) | duplicate atomics in the rewind | requester result | any counter > 1 |
  |---|---|---|---|
  | 4 | 0 | all completed | no |
  | 16 | 3 | all completed | no |
  | 64 | 13 | RETRY_EXC (syndrome 0x15), QP → ERR | no |
  | 200 | 34 | RETRY_EXC (syndrome 0x15), QP → ERR | no |

  So duplicates are absorbed silently up to at least 16 requests back. Somewhere between 16 and 64
  the responder stops answering them: it neither NAKs them nor executes them again, and the requester
  times out. **No atomic was ever applied twice**, so the failure is safe and detectable. I infer,
  without having measured it, that the limit is the responder's read/atomic replay resources
  (`max_rd_atomic`). The probe did **not** overwrite WRITE targets before the rewind, so it cannot
  say whether duplicate WRITEs are executed again.
- **Q4, index field.** One trial, on a fresh QP, **not after a 2RST**. Four WRITEs had ctrl-segment
  index fields 1000–1003 but sat in physical slots 0–3. All 4 executed, and their CQEs reported
  `wqe_counter` 0, 1, 2, 3. The NIC ignores the index field for execution and reports its own WQE
  counter. Combined with the earlier measurement that the counter restarts at 0 after `2RST`
  (gin_recovery, nvshmem_ft), a CQE after a reset carries the NIC's 0-based counter, never a
  preserved logical index. §6.3 draws the consequence.

---

## 12. Biggest risks

1. **Exactly-once at scale is not yet validated.** Q1 held in 28/28 data points, but only 1 trial
   (Mode A) had a non-empty replay. There are none for Mode B, and none with the responder QP driven
   to ERR while requests were in flight: the ERR data points are all at prefixes 0–3 or at the full
   256. A responder whose `next_rcv_psn` behaves differently when the ERR transition lands in the
   middle of a multi-packet message is the remaining gap. Mode A, where the responder stays RTS, is
   covered by the one partial-message trial and remains the safer primary path. Next: inject at or
   before the doorbell with a longer burst, N ≥ 30 per cell (§10).
2. **Device code is header-inlined, and DeepEP legacy forks it.** Transparency needs library device
   changes: the pause gate, the per-QP base in polls (§6.3, now required by Q4), and spin instead of
   assert. NVSHMEM's and GIN's device APIs are compiled into the app's kernels, so apps need **no
   source change but must be recompiled** against the patched headers. More seriously, DeepEP's legacy
   (NVSHMEM) kernels do not call NVSHMEM's device posting code at all. They post and poll through their
   own copy, `csrc/kernels/legacy/ibgda_device.cuh` [source]: own reserve without a slot check, own
   `post_send`, and a `poll_cq` that never checks the CQE opcode. A fix inside NVSHMEM alone does not
   cover DeepEP legacy; that file needs the same gate and base. DeepEP's elastic path uses NCCL GIN
   through NCCL's device headers [source `backend/nccl.cu`], so a GIN fix reaches it with a recompile.
   This makes GIN the better first target (§13).
3. **Fetching atomics / READs executed-but-unacked.** Exactly-once for these needs either a decline
   or a re-issue within the duplicate window. Q3 put that window at ≥ 16 requests absorbed and < 64
   (n=1 per depth; the mechanism, `max_rd_atomic`, is inferred), with a safe RETRY_EXC beyond it.
   DeepEP's low-latency path is dominated by non-fetching signal-adds, which are safe, but its `get`
   and the CST flush are reads. Whether duplicate WRITEs are executed again was not measured.
4. **Pause-gate correctness under the real memory model.** The Dekker argument (§3.2) assumes a
   working system-scope fence on GPU-mapped host memory across PCIe; PeerMappingOverride makes GPU
   doorbells work but the host↔device fence on mapped memory must be validated (a targeted micro-test
   like the prior mailbox `seq/magic` protocol).
5. **Detection latency for RETRY_EXC is 3.6 s** at timeout 14 [measured]; the device wait must block
   that long. Acceptable for fault tolerance, but the device poll timeout (if compiled in) must
   exceed it, and a 3.6 s stall of a collective is a availability, not correctness, cost.
6. **Multi-QP interleave.** A single logical op split across several QPs (DeepEP splits a message
   over QPs) makes the per-QP PSN prefix insufficient to bound a *message*; the recovery epoch must
   cover all QPs of the peer atomically (§6.1). Declined if a message spans QPs whose prefixes
   disagree beyond what replay can reconcile.

## 13. Recommended first implementation step

Land **S1: the device pause gate + block-across-recovery on GDAKI, single QP, single op**, on top
of the existing `gin_recovery` host prepare/commit, gated by the existing flag. Rationale:

- It is the smallest change that proves the **transparency** claim (the reviewer's objection (b)):
  the app runs `put; flush` in a loop, a fault mid-loop is injected, and the loop completes with no
  error and no relaunch — nothing else in the design is needed to demonstrate that.
- GDAKI's wait already spins on `-EIO` and already has an `abortFlag`/timeout hook [source]. Blocking
  across a recovery therefore needs no new device control flow: the pause gate (three words in
  existing padding) plus the per-QP base subtraction in `poll_one_cq_at` and the slot/doorbell
  computation, which Q4 showed is required (§6.3).
- GIN is the better first target. DeepEP's elastic path reaches it through NCCL's device headers
  with a recompile only, whereas DeepEP legacy forks the NVSHMEM device code (§12 risk 2).
- Its probe prerequisites are answered: Q1 (the PSN authority, 28/28) and Q4 (the NIC's own counter,
  so the base is needed). Run the missing Mode B / mid-burst exactly-once cells (§12 risk 1) in
  parallel. They validate S2's replay, not S1's transparency mechanism.

Then S2 (many ops on one QP) directly retires objection (a), and S3/S4 (multi-QP, Mode A) complete
the DeepEP-scale, maximally-transparent story.
