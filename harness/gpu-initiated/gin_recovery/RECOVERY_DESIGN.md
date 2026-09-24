# Design: recovery for GPU-initiated RDMA on NCCL GIN GDAKI

Patch: `gin_recovery.diff`, layered on `../gin/gin_fault_inject.diff` and
`../gin_q4/gin_q4_classify.diff` (NCCL v2.32.3-1). Everything is behind
`NCCL_GIN_FAULT_RECOVERY=1` (default 0) and needs `NCCL_GIN_FAULT_CLASSIFY=1` (the Q4
classifier). This document states the contract, the mechanism, and the argument that a
recovery neither loses nor duplicates an operation. Section 11 lists what the tests changed.

## 1. Contract

- **Flag off:** no new code runs. The GDAKI connect path makes the same DOCA calls with the
  same arguments as the Q4 build (the new PSN parameters default to the stock 0). The
  progress thread takes no extra lock. The behaviour is the Q4 build's.
- **Flag on:** the library recovers only when the preconditions in §3 hold. In every other
  case it declines: the error stays surfaced (`ncclRemoteError` from the device wait and from
  `ncclCommGetAsyncError`), the QPs stay in ERR, and teardown (`ncclCommAbort`) works as in Q4.
  Every wait in the recovery path is bounded.
- The library provides the **mechanism**: fault query, quiescence checks, bilateral QP reset
  with fresh PSNs, and GPU-side state resync. The **application** provides the policy inputs
  that only it can know: that its kernels have stopped, whether the peer is alive, what the
  peer's signal value is, and which operation to replay (§4).

## 2. Fault classes and policy

The Q4 device classifier finds the root-cause CQE (not the polled one, which is normally the
trailing flush 5/0xf9) and publishes it through the host mailbox.

| root cause (status/vendor) | class | decision | why |
|---|---|---|---|
| WR_FLUSH 5/0xf5 (head of SQ) | LOCAL_QP_ERR | recover | the local QP left RTS without an error of its own (transient local ERR, e.g. forced by software) |
| RETRY_EXC 12/0x81, peer alive | RETRY_EXC | recover | no ACK, but the peer process is up (its QP went to ERR, or the path flapped) |
| RETRY_EXC 12/0x81, peer dead | RETRY_EXC | decline | the peer process is gone; there is nothing to reconnect to |
| REM_ACCESS 10/0x88 | REM_ACCESS | decline | deterministic: a replay would hit the same rkey/bounds error |
| REM_INV_REQ 9/0x8a, LOC_PROT, LOC_LEN, REM_OP, RNR_RETRY_EXC, other | - | decline | deterministic or a broken peer |
| WR_FLUSH 5/0xf9 with no root cause in the window | FLUSH_TRAILING | decline | the cause is unknown |

Liveness comes from the application's out-of-band TCP socket on the management network, as in
the CPU harness: `recv(MSG_PEEK|MSG_DONTWAIT)` returning 0 (FIN) or ECONNRESET/EPIPE/ETIMEDOUT/
ENOTCONN means the peer is dead. EAGAIN is no evidence of death. The handshake deadline
(§5) is the second liveness test: a peer that does not answer within it is treated as dead.

## 3. Preconditions (checked; any failure → decline)

1. **Configuration.** GDAKI backend; ring CQ (`DOCA_GPUNETIO_VERBS_CQ_64B`, the stock shape);
   CPU-proxy doorbell mode (the only mode this hardware runs); no companion (counter) QPs;
   the GDAKI context belongs to a user devComm. Collapsed CQs are declined because they are
   untested here. GPU-rung doorbells (`GPU_SM_DB`) are declined by v1 and supported by v2
   (`gin_recovery_gpudb.diff`, §11); BlueFlame, no-DBR and SW-emulated-DBR modes are declined
   by both.
2. **Class** as in §2, reported by the initiator's device.
3. **Quiescence** (§4) on both ranks, verified per QP from the device state:
   `sq_ready_index == sq_rsvd_index` (no WQE half-posted), the proxy doorbell mailbox equals
   `sq_rsvd_index` (every WQE submitted), and the proxy has rung up to it.
4. **Drain.** After the QP is moved to ERR, the CQE of the last posted WQE (index
   `sq_rsvd_index-1`) is present in the CQ ring (owner bit of its lap and matching
   `wqe_counter`), within `NCCL_GIN_RECOVERY_DRAIN_MS` (default 1000). CQEs of one SQ are
   written in order, so every earlier CQE is present too.
5. **Handshake.** The peer answers with a matching token within the deadline.
6. **Signal delta.** The receiver's signal is `expected` or `expected-1` (§7). Anything else
   means an operation was lost or doubled before the recovery started; the recovery declines.
7. **Bounds.** At most 4 recovery attempts per operation (`GIN_REC_MAX_PER_ITER`).

## 4. Quiescence model and what the application must do

GPU producers must stop before any QP is touched, because the reset rewrites the producer
indices the device uses. The model:

1. A device wait (`flush`, `wait`, timeout or blocking) that meets an error CQE returns
   `ncclRemoteError` (Q4). The kernel returns; it posts nothing more.
2. The host waits for the stream (the kernel has exited). Only then does it call
   `ncclGinRecoverPrepare`.
3. The peer's host must not run a kernel that **posts** on the same QPs until the recovery is
   committed. A kernel that only waits on its own signal memory (`waitSignal`) may keep
   running: it touches no QP or CQ state. The recovery code never calls
   `cudaDeviceSynchronize` (it uses a private non-blocking stream) so it does not wait for
   such a kernel.
4. After `ncclGinRecoverCommit` the application relaunches from the failed operation.
   Every `ncclGinRequest_t` and ticket obtained before the fault is void (the WQE index space
   restarts at 0).

A kernel the application launches *while* another kernel still runs (the responder's signal
read, its decline-path release kernel) must not need a local-memory (stack) resize: the driver
resizes local memory only with the device idle, so such a launch waits for the spinning waiter
and, with a blocking waiter, never starts (measured, §11). Such kernels are launched once at
init. The recovery library itself launches no kernel (copies and memsets on its own stream).

The library cannot see kernels, so (3) is a contract, not a check. What it checks is the
device state of each QP (§3.3): a kernel caught in the middle of posting would show
`sq_ready_index < sq_rsvd_index` or an unsubmitted doorbell.

## 5. Protocol

The initiator is the rank whose device reported the error (here the put initiator, rank 0).
The responder is its peer. Messages go over the driver's TCP socket on the management
network (fixed-size records with magic, type, iteration, token).

```
initiator (rank 0)                                   responder (rank 1)
kernel returns ncclRemoteError; stream idle          waiter kernel may still spin on its signal
ncclGinFaultQuery -> class, fingerprint
policy (§2): decline -> send FAIL, stop
ncclGinRecoverPrepare(peer 1):
   pause proxy progress; per QP: check quiescence,
   QP -> ERR, drain; fresh random 24-bit SQ PSN
REQ{iter, class, token_i} ------------------------->
                                                     ncclGinRecoverPrepare(peer 0): same steps
                                                     (its QPs -> ERR: no packet of the old
                                                      incarnation can execute any more)
                                                     V = readSignal (side stream)
                                                     d = expected(iter) - V, must be 0 or 1
                                                     ncclGinRecoverCommit(peer 0, token_i):
                                                       RESET, resync, INIT, RTR(rq_psn =
                                                       token_i.sq_psn), RTS(own sq_psn)
<------------------------------------------ ACK{iter, token_r, d}   (or NACK -> both decline)
ncclGinRecoverCommit(peer 1, token_r)
d == 1: relaunch the put + signal of iter; flush
d == 0: nothing to replay (§7)
DONE{iter} ---------------------------------------->
```

- The responder commits (reaches RTR) before it sends ACK, so the initiator's first
  post-recovery packet always meets a receive-ready QP.
- If the replay fails again (a second fault), the initiator starts a new round for the same
  operation. The responder accepts a REQ for its current operation, or for the one it has
  just completed (the case where the signal landed but the initiator's completion was an
  error).
- Deadline: the initiator waits at most `GIN_REC_HANDSHAKE_MS` (default 3000) for ACK. On
  timeout, NACK, FAIL, FIN or RST it calls `ncclGinRecoverAbort` (resume the proxy; the QPs
  stay in ERR) and declines.
- On decline the initiator sends FAIL. A responder whose waiter is a blocking `waitSignal`
  (which has no abort flag on a user devComm) releases it with a signal to itself over the
  self-loop QP, marks the operation failed without checking its data, and tears down. The
  release kernel is warmed at init (§4).

## 6. Bilateral QP reset and GPU-side state

### 6.1 Which QPs

All QPs of the user GDAKI context to the peer, in every GIN context (4 here), on both ranks,
whether or not they saw an error. Both ends of a pair must be reset together, because each
end's new receive PSN is the other end's new send PSN. Self-loop QPs are not touched.

### 6.2 Connect-time attributes

`gdakiConnectQp` is reused unchanged except for two PSN parameters (stock value 0). When
recovery is enabled the create path keeps a copy of each QP's peer `gdaki_exch_info` and its
LAG port affinity, so the reconnect uses exactly what connect used:

| step | attributes |
|---|---|
| ERR → RESET | `QP_2RST` |
| RESET → INIT | pkey index, port 1, remote write + read allowed |
| INIT → RTR | path MTU = min(local, remote active MTU), dest QPN (stored), AH (stored GID, dlid, hop limit, sgid index, traffic class), `min_rnr_timer` 12, `max_dest_rd_atomic`, atomic mode IB-spec, **rq_psn = peer's new sq_psn** |
| RTR → RTS | `ack_timeout = NCCL_IB_TIMEOUT`, `retry_cnt = NCCL_IB_RETRY_CNT`, `rnr_retry` 7, `max_rd_atomic`, **sq_psn = fresh random 24-bit** |

The RTR/RTS masks are the connect-time masks. DOCA tracks the QP state in software
(`m_current_state`), so a QP that the hardware moved to ERR still reads RTS there; the reset
issues `QP_2ERR` and then `QP_2RST` explicitly, which DOCA accepts from any state.

### 6.3 Device-visible state inventory

After `QP_2RST` the NIC restarts the send queue at WQE counter 0 and expects the WQE with
index 0 in slot 0. The CQ is a separate object and is **not** reset: its producer keeps
counting. Every piece of state that encodes a WQE index or a doorbell must be made
consistent with that:

| state | where | owner | on recovery | why |
|---|---|---|---|---|
| `sq_rsvd_index` | device QP struct | GPU | 0 | next WQE must be index 0 / slot 0, as the NIC expects after RESET |
| `sq_ready_index` | device QP struct | GPU | 0 | the ready CAS loop compares it with the next reserved index |
| `sq_wqe_pi` | device QP struct | GPU | 0 | producer index: in GPU_SM_DB mode the GPU's submit rings only if `atomic_max(sq_wqe_pi, new)` raises it, so a stale value suppresses every doorbell of the new epoch (measured, §11); in CPU-proxy mode used only with `CPU_PROXY_UPDATE_PI` (collapsed CQs) |
| `sq_lock` | device QP struct | GPU | 0 | no holder exists (quiescent) |
| `cq_sq.cqe_ci` | device QP struct | GPU | 0 | consumer index lives in the WQE index space |
| `cq_sq.cqe_rsvd` | device QP struct | host | old `cqe_rsvd` + S (S = WQEs of the ending epoch) | the ring poll reads the CQE of WQE j at CQ position j + `cqe_rsvd`; the CQ producer stands at old `cqe_rsvd` + S (one CQE per WQE, drained), so the first new CQE lands there |
| CQ buffer | GPU memory | NIC | **not** rewritten | every stale entry at a position in the current lap was written in the previous lap, so its owner bit has the wrong parity and it cannot be taken for a new CQE; never-written entries still carry DOCA's init value (owner 1, opcode invalid), which is not valid in lap 0 |
| SQ WQE buffer | GPU memory | GPU | not rewritten | the NIC fetches only up to the doorbell record, which the device writes after it has written the new WQEs |
| SQ doorbell record | host memory (CPU-proxy mode); GPU memory (GPU_SM_DB, v2) | proxy / GPU | 0, while the QP is in RESET (host store / `cudaMemsetAsync`) | the NIC may read it (doorbell recovery); a stale value would make it fetch stale WQEs from slot 0 |
| proxy doorbell mailbox `cpu_db` | host-mapped | GPU (`fetch_max`) | 0 | the GPU publishes new producer indices with `fetch_max`; a stale S would hide them until the new epoch passed S, and no doorbell would ring |
| proxy `sq_wqe_pi_last` | host struct | proxy thread | 0 | the proxy rings only when the mailbox exceeds it |
| host shadow `qp_cpu` | host struct | DOCA host | same values as the device copy | keeps any later DOCA host operation that copies it consistent |
| `last_issued_get`, `last_visible_get` [ctx][peer] | GPU memory | GPU | 0 | they hold WQE tickets (+1) of gets and MCST reads; a stale ticket would make the next flush poll an index of the new epoch that may never exist |
| Q4 sticky error [ctx] | GPU memory | GPU | 0 | otherwise every later blocking flush/wait returns `ncclRemoteError` |
| Q4 host `hasError`, GIN async result | host | Q4 watcher | cleared (the async result only if it still holds the watcher's `ncclRemoteError`) | otherwise `ncclCommGetAsyncError` keeps failing after a successful recovery |
| signal and counter tables, signal shadows | GPU memory | application | untouched | application state; reconciled by §7 |

DOCA ships `doca_gpu_verbs_reset_tracking_and_memory`, which resets most of these fields. It
is not used, for three reasons: it sets `cqe_rsvd` to the ending epoch's WQE count instead of
adding it, which is wrong from the second reset on; it refills the CQ with 0xff, whose owner
bit is valid in odd laps (on sm_90 the ring poll checks only the owner bit, so a refilled slot
in an odd lap would look complete); and it calls `cudaDeviceSynchronize`, which would wait
forever for the responder's still-spinning waiter kernel.

### 6.4 Order inside Commit (per QP)

`QP_2RST` → zero the doorbell record, `cpu_db`, `sq_wqe_pi_last` → write the device QP struct
and the host shadow → clear `last_*_get` → INIT → RTR → RTS. Then, once for the context:
clear the Q4 error state, resume the proxy, and bump the commit counter (the multi-shot test
hook waits on it). The GIN progress thread is paused from the start of Prepare to the end of
Commit or Abort: it skips this context while a flag is set, and Prepare waits until no
progress call is inside the context.

## 7. Replay semantics

The data put is an RDMA WRITE of the same bytes to the same offset: replaying it is
idempotent as long as the receiver has not reused the buffer. In this driver the receiver
does not touch the buffer until the operation is confirmed.

The signal is a remote atomic ADD (`ncclGin_WeakSignalInc` → `SIGNAL_OP_ADD 1`); it is not
idempotent. The rule:

- The receiver reads its signal V **after** its QPs are in ERR and the initiator's QPs are in
  ERR. From then on no packet of the old incarnation can execute (the responder QP is in ERR
  or RESET, and a late packet cannot match the fresh expected PSN except with probability
  2^-24). So V is final for the old incarnation.
- One operation adds exactly 1, and all earlier operations completed (their flushes returned
  success, which requires the ACK of their atomic). Hence V ∈ {expected-1, expected}.
- d = expected − V. d = 1: the atomic did not execute; the initiator replays put + Inc.
  d = 0: the atomic executed. Because RC executes the requests of one QP in order and the
  WRITE precedes the atomic, the whole WRITE was placed before the ADD ran, so the data is
  complete; nothing is replayed. Any other d: decline.
- A replay that fails starts a new round, which reads V again. So an ADD that executed during
  a failed replay is counted, not repeated.

This gives each operation exactly one successful ADD. A pipelined application with k
operations outstanding would get d ∈ [0, k] and would replay the last d of them in order
(RC order again), with one ADD each; GIN also offers `SignalAdd{value}` but forbids mixing it
with `Inc` without a reset. This driver has one operation outstanding (lockstep).

## 8. Safety argument

Invariants, each with the reason it holds:

1. **No old-incarnation operation executes after V is read.** Both QPs of every pair are in
   ERR before the responder reads V (initiator: Prepare before REQ; responder: Prepare before
   reading V). A QP in ERR or RESET executes nothing. After RTR the expected PSN is fresh.
2. **V is final and every earlier operation is in it.** By 1 and the lockstep: an earlier
   operation's flush returned success only after its atomic was ACKed.
3. **Exactly the missing work is replayed.** By §7.
4. **The new epoch's WQEs are the only ones the NIC fetches.** RESET restarts the NIC at
   counter 0; the device restarts at index 0; the doorbell record and the proxy mailbox are 0
   before RTS; the NIC fetches only up to the doorbell record, written after the new WQEs.
5. **No stale CQE is taken for a new completion.** The drain guarantees the CQ producer is
   exactly old `cqe_rsvd` + S before the reset; nothing more is written for the old epoch (no
   WQE beyond S exists and the QP is reset). The new mapping starts at that position;
   stale entries at positions ≥ it have the wrong owner parity (§6.3). On sm < 90 the poll
   also matches `wqe_counter` to the 16-bit index.
6. **No stale doorbell.** The proxy is paused across the whole reset and its state is zeroed
   with the mailbox; it resumes only after the device struct holds the new indices.
7. **No half-reset pair is used.** The initiator replays only after both Commits succeeded
   (the responder's before ACK, its own after). Any failure before that declines; the QPs are
   left in ERR, so nothing is sent on a half-configured pair.
8. **Nothing blocks forever.** Drain, handshake and per-operation attempts are bounded; the
   recovery never waits for a kernel.

## 9. Decline paths

- Class not recoverable, peer dead, a precondition fails, NACK, deadline, a DOCA modify
  error, or too many attempts: the initiator sends FAIL (best effort) and stops. The comm
  stays in error (`ncclRemoteError` from `ncclCommGetAsyncError`); the application tears it
  down with `ncclCommAbort`, which returns (Q4 measured GDAKI teardown after an error as
  clean).
- A responder that gets FAIL releases its own blocking waiter (self signal), reports the
  failure, and tears down.

## 10. Limitations and residual risk

- **One initiator per pair.** Both ranks initiating at once is not handled (the protocol has
  no tie-break); the driver only initiates from the put side.
- **Quiescence of kernels is a contract**, checked only through QP state (§4).
- **LOCAL_QP_ERR is assumed transient.** A local fault that recurs (e.g. a hardware error
  behind the ERR) is bounded by the attempt cap and then declined.
- **CPU-proxy doorbell, ring CQ, no counters** only (§3.1).
- **Stale PSN collision** probability about 2^-24 per stray packet of the old incarnation.
- The reset touches all four GIN contexts' QP pairs, including idle healthy ones.

## 11. What the tests changed

- **The mechanism worked as designed on the first cluster run** (F1 and F3, both wait modes).
  In particular the NIC restarts the SQ at WQE counter 0 after `QP_2RST` (the first replayed
  WQE completed with `wqe_counter` 0 at CQ position old `cqe_rsvd` + S), and the stale ring
  entries were never taken for new completions (all later polls matched), without refilling the
  CQ.
- **Two faults on one operation.** A shot fired inside the commit of the previous recovery hits
  the replay; the replay fails with LOCAL_QP_ERR (or RETRY_EXC for F3) and a second round reads V
  again and replays again. So *faults* and *recovered operations* differ: five faults gave five
  recovery rounds but four affected operations in every multi-fault run.
- **Local-memory resize serialises kernels** (driver): the receiver's release kernel (336-byte
  stack frame; the waiter has none) did not start while the waiter spun: in timeout mode it
  started only when the waiter timed out (4.1 s), in blocking mode never (receiver capped at
  30 s). Launching it once at init fixed it. Added to §4.
- **Barrier race inherited from the Q4 driver** (driver): the receiver poisoned its buffer after
  acknowledging the barrier; once, right after a driver-module reload, its first `cudaMemset` was
  slow enough for the put to land first, so the signal said "done" over a poisoned buffer. The
  receiver now poisons before the acknowledgement.
- **The d = 0 branch** cannot be reached by the fault hook in practice (it needs the error to hit
  between the responder executing the ADD and the ACK arriving), so it is exercised by a forced
  recovery after a completed operation (`D0` runs).
- **Negative controls support invariants 5 and 6 (§8).**
  - With DOCA's non-cumulative `cqe_rsvd`, the second recovery's replay executed on the wire,
    but the GPU polled a slot holding a stale previous-epoch CQE (`wqe_counter` 23 where 1 was
    expected) and timed out.
  - Leaving the proxy mailbox at its old value meant the first replay was never doorbelled.
  - Both were declined cleanly (`NCCL_GIN_RECOVERY_DIAG`, results in `diag/negative/`).
- **Test hook.** A shot delay of 0 after a commit usually lost the race to the replay (the replay
  completes in ~0.3 ms, the hook's four modify commands take ~1.2 ms), so the fault landed on the
  next operation. The hook gained delay -1 (fire inside the commit, after RTS), which hits the
  replay deterministically.
- **GPU doorbells (v2, `gin_recovery_gpudb.diff`).**
  - Since PeerMappingOverride=1 became permanent, DOCA resolves every GDAKI QP to `GPU_SM_DB`.
    The GPU rings the UAR doorbell and writes the doorbell record, which lives in GPU memory.
    There is no proxy thread, mailbox or proxy counter.
  - v1 declined (safely) in this mode. v2 checks quiescence against `sq_wqe_pi` and the
    GPU-memory record, and zeroes the record with `cudaMemsetAsync`; the rest of the protocol
    and the inventory are unchanged.
  - Measured negative controls:
    - Leaving `sq_wqe_pi` stale breaks recovery: no doorbell ever rings for the replay.
    - Leaving the GPU doorbell record stale did not (4/4 recoveries), because the GPU's first
      submit rewrites it. Its reset stays as a defensive step.
