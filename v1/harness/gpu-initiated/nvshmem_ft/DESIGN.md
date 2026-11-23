# Design: fault tolerance for NVSHMEM IBGDA (GPU NIC handler)

Patch: `nvshmem_ibgda_ft.diff`, layered on NVSHMEM `7bb2e99c` +
`../nvshmem/nvshmem_ibgda_fault_inject.diff` + `../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff`.
Everything is behind `NVSHMEM_IBGDA_FT=1` (default off). This document states the contract, the
mechanism, and the argument that a recovery neither loses nor duplicates an operation. It follows
`../gin_recovery/RECOVERY_DESIGN.md`; the differences come from NVSHMEM's collapsed CQ and its
GPU-rung doorbells. Section 10 lists what the tests changed.

## 1. Contract

- **Flag off:** the device reads one `__constant__` pointer (`state->ft`, NULL) per CQ poll and
  then runs the stock loop; the host creates no thread and no buffer. The connect path issues the
  same DEVX commands with the same values (the new PSN parameters default to the stock 0).
- **Flag on, classification:** a device wait on a send CQ that meets an error CQE records the
  root cause, publishes it to a host-mapped mailbox and returns an error instead of spinning or
  reporting success. `nvshmem_quiet()` itself still returns `void`; the kernel learns the result
  from `nvshmemx_ibgda_ft_status(pe)`, or uses `nvshmemx_ibgda_ft_quiet_bounded(pe, budget)`,
  which returns 0 / -1 (error) / -2 (budget expired).
- **Flag on, recovery:** the transport exports a mechanism (`nvshmemt_ibgda_ft_query / prepare /
  commit / abort / mark_failed`); the application supplies what only it knows: that its kernels
  have stopped posting, whether the peer is alive, the receiver's signal value, and which
  operations to replay (section 4). Recovery runs only when the preconditions of section 3 hold; in
  every other case it declines, the QPs stay in ERR, and teardown returns (section 8).

## 2. Classification on a collapsed CQ

NVSHMEM's send CQs are collapsed (`cc=1`): the NIC writes every CQE to slot 0. After an error the
NIC writes the root-cause CQE and then one `WR_FLUSH 5/0xf9` for each WQE behind it, the first
≈59 us later (the CQE-sequence measurement, `../cqe_seq/`). `ibgda_poll_cq` waits until the slot's `wqe_counter` reaches the index it
waits for, which is the *last* posted WQE, so the stock wait always ends on a trailing flush and
(with the release build's `assert` compiled out) reports success.

The classifier therefore reads the slot's opcode **inside the spin loop** of every poll
(`quiet`, the WQE-slot wait, the bounded quiet). One 32-bit load of CQE word 15 returns both
`wqe_counter` (bytes 60-61) and `op_own` (byte 63), so the loop issues no more loads than the stock
one. The first time it sees opcode 0xd/0xe it takes a
consistent 64-byte snapshot (word 15, which holds `wqe_counter` and `op_own`, equal before and
after the copy), maps (syndrome, vendor_err) with the rdma-core table (0x05/0xf5 LOCAL_QP_ERR,
0x05/0xf9 FLUSH_TRAILING, 0x04 LOC_PROT, 0x12 REM_INV_REQ, 0x13 REM_ACCESS, 0x15 RETRY_EXC, 0x16
RNR_RETRY_EXC, ...), and stores a sticky per-QP record in the 24 formerly unused padding bytes of
the QP's management variables (`ft_state`, `ft_fp`, `ft_wqe`, `ft_aux`, `ft_gtime`). The first
recorder wins (`atomicCAS`); a record that holds only a trailing flush can be replaced once by a
later root cause (state 3 -> 2). Every later poll of that QP returns -1 at its first read of the
slot: after a QP error the slot holds an error CQE (every later completion is a flush) until
recovery refills it, so no separate sticky check is needed on the fast path.

The record is also written to a 16-slot mailbox of 256-byte records in host-pinned mapped memory:
invalidate `magic`, body with `st.relaxed.sys`, `__threadfence_system`, `seq`, fence, `magic`.
A host watcher thread in the transport polls the mailbox (default every 50 us), logs one line with
the status/vendor_err pair, class, cause and action (wording of `harness/common/probe.c classify()`), queries
the QP with DEVX `QUERY_QP`, and keeps the first record for `nvshmemt_ibgda_ft_query()`.

**When the root cause is lost.** The in-loop read captures the root cause only if some thread is
polling the CQ during the ≈59 us before the first trailing flush. That holds when the wait follows
the posts (put+signal then quiet; a burst then quiet; RETRY_EXC, which arrives seconds later while
the wait spins). It fails when the kernel posts and then does other work for longer than that
window before it waits (`nbi` puts overlapped with compute). For that pattern the patch offers a
**device sentinel** (`nvshmemx_ibgda_ft_sentinel(poll_ns)`): one thread, launched by the
application in its own kernel on a non-blocking stream, polls every RC/DCI slot and records the
first error CQE of each QP. Trade-offs: it occupies one warp slot of one SM for the life of the
job, it must be started after every kernel of the application has been launched once (a kernel
that needs a larger local-memory reservation cannot start while another kernel runs), and it must
be stopped (`nvshmemt_ibgda_ft_sentinel_stop`) before teardown. Section 10 measures both paths.

## 3. Preconditions (checked; any failure -> decline)

1. **Configuration.** IBGDA with the **GPU NIC handler** (the GPU writes the doorbell record and
   rings the UAR). The CPU-proxy handlers keep host-side producer state and, in this NVSHMEM
   version, write the wrong doorbell-record word (`../nvshmem_rootcause/`); `prepare` returns
   -2 for them. RC QPs to the peer (1 per PE here; up to 8 per peer are handled). DCIs may exist;
   a DCI that is not in RTS is reset locally at commit.
2. **Class** (application policy, section 5): LOCAL_QP_ERR recover; RETRY_EXC recover only if the
   OOB socket shows the peer alive; REM_ACCESS, REM_INV_REQ, LOC_*, RNR, FLUSH_TRAILING (root cause
   unknown), a wait that expired without an error record, and anything else: decline.
3. **Quiescence** per QP, from the device's own variables (copied with a non-blocking stream):
   `post_send_lock == 0`, `resv_head == ready_head == prod_idx` (no WQE half-written, every ready
   WQE rung), `ibuf.head == ibuf.tail` (no fetch slot in use).
4. **Drain.** After the QP is moved to ERR, `QUERY_QP.hw_sq_wqebb_counter` must reach the device
   producer index within `NVSHMEM_IBGDA_FT_DRAIN_MS` (default 1000): the NIC has flushed every WQE
   the device posted. (This relies on the GPU handler keeping the send word of the doorbell record
   current; with the CPU proxy's word-0 bug the counter drops to 0 at ERR, measured in
   `../nvshmem_rootcause/`.)
5. **Handshake.** The peer answers REQ with ACK and a matching token within 5 s.
6. **Signal delta.** The receiver's signal V satisfies `expected - burst <= V <= expected`.
7. **Bounds.** At most 6 recovery rounds per operation.

## 4. Quiescence model and what the application must do

1. A device wait that meets an error returns (-1, or `nvshmem_quiet` returns and
   `nvshmemx_ibgda_ft_status` is non-zero). The kernel returns; it posts nothing more.
2. The host waits for that kernel (stream) before `nvshmemt_ibgda_ft_prepare`.
3. The peer must not run a kernel that posts on the same QPs until it has committed. A kernel that
   only waits on local memory (`nvshmem_signal_wait_until`) may keep spinning: the recovery code
   touches no memory it reads and launches no kernel (it uses `cudaMemcpyAsync`/`cudaMemsetAsync`
   on its own non-blocking stream).
4. After commit every device index restarts at 0; any ticket or index the application kept from
   before the fault is void.

The library cannot see kernels; (3) is a contract. What it checks is the device state of each QP
(section 3.3): a kernel caught posting would show `resv_head != ready_head` or `ready_head !=
prod_idx`.

## 5. Protocol (management-network TCP socket of the driver)

```
initiator (PE0)                                     responder (PE1)
kernel returns error; stream idle                   waiter may still spin on its signal
ft_query -> class, status/vendor_err
policy: decline -> FAIL, ft_abort, teardown
ft_prepare(peer): quiescence, QPs -> ERR,
   drain, fresh random 24-bit SQ PSNs
REQ{it, class, token_i} --------------------------->
                                                    ft_prepare(peer): same (its QPs -> ERR)
                                                    V = signal (side stream D2H)
                                                    d = expected(it) - V, must be in [0, burst]
                                                    ft_commit(peer, token_i): RESET, device
                                                      resync, INIT, RTR(rq_psn = token_i.psn),
                                                      RTS(own psn)
<--------------------------------------- ACK{token_r, d, V}   (or NACK -> decline)
ft_commit(peer, token_r)
replay the last d put+ADD operations (d = 0: none)
a failed replay -> new round (reads V again)
DONE{it} ------------------------------------------>
```

- The responder commits (RTR) before it sends ACK, so the first replayed packet meets a
  receive-ready QP with the expected PSN.
- The responder accepts a REQ for its current operation or the one it just verified (the ADD
  executed but the initiator's completion was an error: d = 0).
- On FAIL (or EOF on the socket) the responder releases its own waiter by writing a cancel marker
  (`1 << 40`) into its signal with a host copy on a non-blocking stream, marks the transport
  failed and tears down.

## 6. Bilateral reset and device-side state

### 6.1 QPs

All RC QPs between the pair, on both sides, whether or not they saw an error (each end's new
receive PSN is the other end's new send PSN). Local DCIs not in RTS (the fault hook moves every QP
of the PE to ERR) are reset with their stock DCI attributes; they have no fixed peer.

### 6.2 Connect-time attributes

`ibgda_setup_rc_endpoints` now keeps each RC endpoint's peer handle (QPN, LID, GID) and peer PE.
Commit calls the stock transition functions with them: `ibgda_qp_rst2init` (port, pkey,
rwe/rre/rae, atomic mode), `ibgda_rc_init2rtr` (MTU, remote QPN, `min_rnr_nak`, `log_rra_max`,
address path built from a fresh AH on the same attributes; the old AH is destroyed first) with
`next_rcv_psn = peer's new PSN`, and `ibgda_qp_rtr2rts` (ack every packet, `log_sra_max`,
`retry_count`, `rnr_retry 7`, `ack_timeout = NVSHMEM_IB_TIMEOUT`) with `next_send_psn = own new
PSN`. The only new values are the two PSNs (stock: 0 on both).

### 6.3 Inventory of device-visible state

After `2RST` the NIC restarts the send queue at WQE counter 0 and expects WQE 0 in slot 0. Every
piece of state that encodes a WQE index or a completion must agree with that before RTS.

| state | where | written by | on recovery | why |
|---|---|---|---|---|
| `mvars.tx_wq.resv_head` | GPU (QP struct) | GPU | 0 | next reserved WQE must be index 0 = slot 0 |
| `mvars.tx_wq.ready_head` | GPU | GPU | 0 | the submit CAS compares it with the next reserved index; quiet waits for it |
| `mvars.tx_wq.prod_idx` | GPU | GPU (`atomicMax`) | 0 | `atomicMax` would ignore every new index below the old one: no doorbell record update, no ring |
| `mvars.tx_wq.cons_idx` | GPU | GPU (`atomicMax`) | 0 | a stale value >= the new indices makes every quiet return at once (silent success) |
| `mvars.tx_wq.get_head / get_tail` | GPU | GPU | 0 | fetch tickets in the WQE index space; a stale head would make quiet issue a CST poll on an index that never completes |
| `mvars.post_send_lock` | GPU | GPU | 0 | no holder (quiescent) |
| `mvars.ibuf.head / tail` | GPU | GPU | 0 (equal before) | fetch-slot ring; checked equal at prepare |
| `mvars.ft_*` (sticky record) | GPU | GPU | 0 | otherwise every later wait returns -1 |
| collapsed CQ buffer (slot 0) | GPU | NIC | refilled with 0xff (creation pattern) while the QP is in RESET | the slot still holds the last old-epoch CQE (an error with `wqe_counter` near the old producer): its opcode would be taken as a new error, and its `wqe_counter` would satisfy the first new wait before the NIC completed anything. 0xff = opcode invalid, `wqe_counter` 0xffff, the state `ibgda_poll_cq` is written for |
| QP doorbell record (send word 1, receive word 0) | GPU (GPU handler) | GPU | 0 | the NIC reads the record (e.g. at state changes); a stale producer would make it fetch old WQEs from slot 0 |
| SQ WQE buffer | GPU | GPU | not rewritten | the NIC fetches only up to the doorbell producer, which the device writes after the new WQEs |
| UAR/BlueFlame doorbell | NIC BAR | GPU | nothing | write-only register, no state |
| CQ doorbell record / EQ | GPU / NIC | - | nothing | NVSHMEM never arms or consumes it (overrun ignore) |
| DCI QP structs + CQs | GPU | GPU/NIC | same as RC, only for a DCI not in RTS | local reset |
| `ft_dev.nerr`, host record | GPU / host | GPU / watcher | cleared | `nvshmemt_ibgda_ft_query` reports no error after a commit |
| host `rc_h` cache | host | host | untouched | its mvars were zero at setup and are only copied back when QPs are added |
| rkeys/lkeys, DCT table, signal and data buffers | GPU | host / application | untouched | not per-QP state; the application reconciles its signal (section 7) |

Order per QP: `2RST` -> refill the CQ and zero the doorbell record (stream sync) -> zero the
management variables (sync) -> INIT -> RTR -> RTS. The CQ goes first so that a running sentinel
never sees a stale error CQE together with a cleared sticky record.

## 7. Replay semantics

The data put is an RDMA WRITE of the same bytes to the same offset: idempotent while the receiver
has not consumed the buffer (lockstep driver). The signal is a remote atomic ADD 1 per operation:
not idempotent.

- The receiver reads V after both ends of every QP pair are in ERR (initiator: prepare before REQ;
  responder: prepare before the read). A QP in ERR or RESET executes nothing, and after RTR the
  expected PSN is fresh, so V is final for the old incarnation.
- Operations of one QP execute in order, and each WRITE precedes its ADD; all earlier operations
  completed (their waits succeeded, which needs the atomic's ACK). With `burst` operations in
  flight V = expected - d with d in [0, burst], and exactly the last d operations are missing.
- d > 0: replay the last d put+ADD operations (data again, one ADD each). d = 0: every ADD
  executed, so every WRITE before it did too: replay nothing.
- A replay that fails starts a new round, which reads V again; an ADD that executed during a failed
  replay is counted, not repeated.

## 8. Safety argument

1. **No old-incarnation operation executes after V is read** (section 7, first point).
2. **V is final and every earlier operation is in it** (lockstep + in-order execution).
3. **Exactly the missing work is replayed** (section 7).
4. **Only new-epoch WQEs are fetched.** RESET restarts the NIC at counter 0; the device restarts
   at index 0; the doorbell record is 0 before RTS; the NIC fetches only up to the record, which the
   device writes after the new WQEs.
5. **No stale completion is taken for a new one.** Drain ensures the NIC wrote its last old-epoch
   CQE before RESET; after `2RST` it writes none for the old epoch; the slot is refilled after
   `2RST`, so the first new wait sees either the creation pattern or a new-epoch CQE.
6. **No half-reset pair is used.** The initiator replays only after both commits succeeded (the
   responder's before ACK, its own after). A failure before that declines with the QPs in ERR.
7. **Nothing blocks forever.** Drain, handshake, receiver waits and rounds are bounded; the library
   waits for no kernel.

## 9. Decline and teardown

`nvshmemt_ibgda_ft_abort(peer)` leaves the QPs in ERR and sets a new transport attribute bit
(`NVSHMEM_TRANSPORT_ATTR_FT_FAILED`). The host library (`barrier.cpp`, `init.cu`) then skips
the device barrier in `nvshmem_malloc/free/barrier_all` and in `nvshmem_finalize` (plus the quiet
that follows it in finalize): a device barrier needs the peer's atomics, which cannot arrive over a
QP in ERR or from a dead process, and it is what made `nvshmem_finalize` hang in `../nvshmem/`.
The TCP bootstrap barrier of finalize ("all previous ops are complete") is skipped as well: after an
abort every QP of the pair is in ERR, so nothing can still write into this PE's memory, and with a
dead peer that barrier retries `connect()` 20000 times (22.9 s measured). The rest of finalize
(freeing the heap, destroying QPs in ERR, closing the device) is unchanged and returned in every
trial. Consequence: after a decline the job's collectives are gone; the application tears down.

## 10. What the tests changed

- **The mechanism worked on the first cluster run** (F1 and F3, both wait modes): after `2RST` the
  NIC restarted the send queue at WQE counter 0 (the replay completed with `wqe_counter` 1 at
  `ready_head` 2), and the refilled slot was never taken for a completion.
- **The transport connects lazily.** `nvshmemx_init_attr` returns before the IBGDA plugin is
  loaded; it is loaded and connected at the first symmetric allocation. The driver resolves the FT
  API after its first barrier.
- **Teardown with a dead peer.** With the device barriers skipped, `nvshmem_finalize` still took
  22.9 s: the TCP bootstrap barrier retried `connect()` 20000 times. It is skipped too once the
  transport is marked failed (18-19 ms after the change). Without the patch the device barrier
  hangs for good (flag-off runs).
- **A killed peer's socket closes before its QPs stop answering.** Puts issued in the first ≈1 ms
  after the FIN still completed; the first put that the dead QP no longer ACKed ended in RETRY_EXC
  3.6-3.8 s later. The driver therefore keeps posting after the FIN until the RDMA error, and the
  kill time is taken on sunny (the runner's own timestamp included the ssh round trip).
- **Where the slot is read decides what is classified** (README, capture study): at the stock
  position (the CQE that ends the wait) 24/24 faults read as FLUSH_TRAILING 5/0xf9; inside the
  spin loop the root cause is kept whenever the wait is spinning when it arrives; with the device
  sentinel it was kept in every pattern, including 2 ms of compute between post and wait.
- **The sentinel's two hazards happened.** (a) The driver's F2b step called
  `cudaDeviceSynchronize`, which waits for the never-ending sentinel: the process hung until its
  bound (fixed: `cudaStreamSynchronize(0)`). (b) A kernel that was not launched once before the
  sentinel started (the latency kernel) never started (local-memory sizing needs an idle device,
  as in `../gin_recovery/`); warming it fixed it. Both runs are kept under `results/b1/`.
- **Overhead.** The first version read `op_own` and the sticky state with separate loads in every
  spin iteration and checked the sticky state on entry: +0.58 us p50 at 4 KiB (+4.6 %). The final
  version reads word 15 once per iteration (section 2).
