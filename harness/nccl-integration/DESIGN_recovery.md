# Design: safe in-tree NCCL RDMA recovery (Stage 1)

Patch: `net_ib_fault_recovery.diff`. It changes only `src/transport/net_ib.cc`
in NCCL v2.23.4-1, and all of it sits behind `NCCL_RDMA_FAULT_RECOVERY=1` (the default is 0).
This document describes the code as it is now. The line numbers in `README.md` refer to the
patched file.

## 1. Contract

With the flag **off**, the IB transport makes the same verbs calls with the same arguments,
in the same order, and returns the same results as stock. The only differences are extra
struct fields and a few stores to them that nothing reads.

With the flag **on**, the transport is never worse than stock:

- It recovers only when it can show recovery is correct (§3).
- In every other case it fails the way stock does (`ncclRemoteError` from `ncclIbTest`).
- It never blocks the proxy thread on a socket. Every wait is bounded in time.
- It never completes a request whose data did not arrive.
- It never silently drops a valid completion.

Stage 2 is **not** attempted: there is no replay when several requests are outstanding.
When the §3 preconditions do not hold, the patch declines.

## 2. Why the previous version was unsafe (and what replaced it)

| Defect | Previous behaviour | Now |
|---|---|---|
| C1 | Acted on the request being *tested* (`r`), never decoded the failed CQE's `wr_id`. Returned at the first error, which dropped the rest of the batch. | The whole batch is consumed with the stock decoding (`ncclIbFrCompleteWc`). The failed request is decoded from `wc->wr_id`. The responder picks the receive by the CTS FIFO sequence number carried in the REQ, not by `r`. |
| C2 | ERR→RESET on both QPs discarded other posted receives, un-ACKed CTS writes and other sends' WRITEs. A blind CQ drain discarded valid completions. | Quiescence is checked on **both** sides before any QP is touched (§3). Reset-time CQEs are dropped only if they belong to the recovered request; any other CQE is either consumed like `ncclIbTest` would, or the recovery fails (§4.3). |
| M1 | Multi-QP/NIC went through the reset first and was declined only afterwards. | Configuration gate before any handshake: `nqps==1 && ndevs==1 && nreqs==1`, checked on both sides, including the REQ's `nqps`. |
| M2 | Blocking `ncclSocketSend/Recv` on the proxy thread. Both ranks injecting caused a deadlock. | Non-blocking state machine driven by successive `ncclIbTest` calls, with a deadline (`NCCL_RDMA_FAULT_HANDSHAKE_MS`, default 2000). |
| M3 | `ncclSocketReady` is not a liveness check. | `recv(fd, MSG_PEEK\|MSG_DONTWAIT)`: 0 means FIN, ECONNRESET/EPIPE/ETIMEDOUT/ENOTCONN mean RST/TCP error, EAGAIN means no evidence of death (§6). |
| M4 | The proxy keeps calling `test` after an error. A later FLUSH could then start a recovery on an already-failed comm. | Sticky per-comm latch (`ncclIbFrFailed`). Every later test/isend/irecv returns the error. |
| M5 | Treated NAK classes as recoverable. | Only `WR_FLUSH_ERR` is recoverable (§7). |
| M6 | The driver read `rbuf[0]` on rank 0 only and printed "ok" whatever the value. | Per-rank, per-iteration, per-index inputs. The whole rbuf is poisoned beforehand, then compared bit-exactly on every rank. Exit is non-zero on any mismatch, error or timeout. |
| minor | Snapshot taken with the flag off; `faultRetries` never reset; responder wait of about 18 ms; different QP access flags, lost `override_tc`/ECE; stale header comment; deterministic PSN. | All fixed (see README table). |

## 3. Preconditions (all must hold, otherwise the stock error is returned)

1. **Fault class.** The first error CQE of the incident is `IBV_WC_WR_FLUSH_ERR` on the **send**
   comm: the local QP left RTS without a completion error of its own (a transient local ERR,
   for example `NCCL_RDMA_FAULT_INJECT`). The recv comm never initiates, and an error CQE on
   it fails the comm.
2. **Configuration.** `nqps == 1`, `ndevs == 1`, and the failed send has `nreqs == 1`
   (the responder also requires the receive to have `nreqs == 1` and the REQ to have `nqps == 1`).
3. **Quiescence, checked before anything is reset:**
   - Initiator: the failed request F is decoded from `wc->wr_id` (low byte; a `BODY` tag marks
     the unsignaled data WRITE). F must be the **only** request of the comm with outstanding
     completions. Every CQE already in the CQ is consumed first, so a completed older send
     does not count.
   - Responder, on receiving a REQ: first consume every CQE already in the CQ. Then:
     - the receive R whose CTS carried the REQ's FIFO sequence number is outstanding;
     - R's data has not been consumed (`recv.arrived == 0`) and `REQ.size <= R.postedSize`;
     - **no other request** has outstanding completions, so no other receive is posted and
       no other signaled CTS write is pending;
     - no GPU-flush read is in flight. This one is waited for, with a bound of
       `HANDSHAKE_MS/4`, because a flush read completes in microseconds.
4. **Health.** No async fatal event is recorded on the comm or its device (NCCL never clears
   those counters). The peer's OOB socket shows no FIN/RST.
5. **Bounds.** At most 3 initiations per comm (answering is not capped), and at most one
   replay/re-post per request.

## 4. Why a reset under these preconditions loses nothing

### 4.1 What is on the two QPs

- **Send comm QP.** Its SQ carries only `ncclIbMultiSend` WRITEs. It never posts receives;
  CTS writes arrive from the peer and are not posted locally. Precondition 3 leaves only
  F's WRs (one `WRITE_WITH_IMM`, plus one unsignaled `WRITE` if adaptive routing splits it).
  All of them are flushed.
- **Recv comm QP.**
  - The RQ holds only R's WQE: every other receive has completed.
  - The SQ holds only CTS writes. The CTS writes for R and for every older receive were
    **delivered**: F exists because the sender read R's CTS from its FIFO, and one RC QP
    delivers its CTS writes in order.
  - A CTS for a newer receive would mean a newer receive is outstanding, which
    precondition 3 excludes.
  - A signaled CTS completion can be pending only for R itself. R's event count is rebuilt
    explicitly.
- The GPU-flush QP (recv comm) shares the CQ but is never reset. Its CQEs are recognised by
  `qp_num` and consumed normally.

### 4.2 Order of operations

```
initiator                                      responder
error CQE(s) -> consume whole batch + CQ
checks 1-5 -> REQ{seq, fifoIdx, size, psn_s}
QP stays in ERR; test() returns not-done;      REQ read on any test()/irecv() of the recv comm
isend() returns NULL                           consume CQ; checks 2-4 on its side
                                               fail -> NACK, latch FAILED (nothing reset)
                                               ok  -> QP RTS->ERR
                                                      drain until R's RQ WQE terminates (<= min(HANDSHAKE_MS/10, 100ms))
                                                      QP ->RESET, drain again
                                                      ->INIT->[set_ece]->RTR(rq_psn=psn_s)->RTS(sq_psn=psn_r)
                                                      re-post exactly R's WQE, R.events = 1
                                                      ACK{seq, fifoIdx, psn_r}; irecv() held
ACK -> QP ->RESET, drain,
->INIT->[set_ece]->RTR(rq_psn=psn_r)->RTS(sq_psn=psn_s)
replay F (same WR shape as ncclIbMultiSend), F.events = 1
DONE{seq} -------------------------------------> back to idle, irecv() allowed again
```

### 4.3 Completions of the old QP incarnation (`ncclIbFrDrainOldQp`)

- **CQE of another QP** (GPU flush). A success is consumed like `ncclIbTest` would. An error
  makes the recovery fail.
- **CQE of the reset QP that belongs to F/R.** It is dropped, because the re-post and the
  replay re-create exactly one completion for it. This covers R's recv flush, R's own CTS
  (signaled or not), F's flushed WRs, and R's recv *success* if its data landed just before
  the reset. In that last case the replay rewrites the same bytes and R still completes once.
- **Success CQE of any other request.** It is consumed normally, never dropped. If that
  request has no outstanding completion, the CQE contradicts precondition 3 and the recovery
  fails.
- **Flushed unsignaled CTS write of a receive that already completed.** It is dropped: the
  write was delivered, and its success would not have produced a CQE.
- **Anything else** means precondition 3 was violated, and the recovery fails.
- **Responder ordering.** RQ completions of one QP are in order. So once R's WQE has
  terminated, every earlier receive completion has been consumed before RESET. This matters
  on mlx5, whose `modify_qp(RESET)` removes the QP's remaining CQEs from the CQ
  (`mlx5_cq_clean`). The drain after RESET covers providers that leave CQEs in the CQ. It
  assumes, as mlx5 guarantees, that no CQE is written for the QP after `modify_qp(RESET)`
  returns.

### 4.4 Why the re-posted receive can only be consumed by the replay

- After the reset, R's WQE is the first WQE in the RQ.
- The initiator posts the replay as the very first WR after RTS. `isend()` returns NULL while
  a handshake is in progress, and RC delivers in order.
- The responder posts no new receive (and so no CTS) until DONE arrives.
- RDMA WRITE is idempotent: the replay writes the same bytes to the same buffer, and that
  buffer is still reserved because R is still outstanding. Its lkey and rkey are unchanged.
- The imm_data (the size) is the same.
- Fresh random 24-bit PSNs on both sides make it unlikely (about 2^-24 per packet) that a
  stale packet of the old incarnation lands on the expected PSN.

## 5. Protocol details

- **Channel.** `base.sock`, the comm's OOB TCP connection. It stays open, and stock NCCL
  does not use it after connection setup. TCP_NODELAY is set by NCCL.
- **Message.** A fixed 40-byte `ncclIbFrMsg`: magic, type (REQ/ACK/NACK/DONE/FAIL), seq,
  nqps, fifoIdx, psn, size, reason.
- **I/O.** Non-blocking `send/recv(MSG_DONTWAIT)` with per-comm offsets: partial reads and
  writes resume on the next call, and nothing ever blocks.
- **Stream desync.** A bad magic latches the comm and abandons the channel.
- **Initiator states.** `Idle -> InitWait -> Idle` (recovered) or `-> Failed`.
  - `InitWait` ends on ACK, NACK or FAIL, on socket close, on an async fatal event, or when
    the deadline expires (`NCCL_RDMA_FAULT_HANDSHAKE_MS`, default 2000 ms).
  - The deadline is checked before a buffered reply is used, so a late ACK is never acted on.
  - On timeout the initiator sends FAIL (best effort).
  - In `Idle` the send comm keeps flushing a pending DONE or FAIL and reads its socket, so a
    FAIL from the responder latches it too (`ncclIbFrInitiatorIdle`).
- **Responder states.** `Idle -> RespPending -> RespAcked -> Idle`, or `-> Failed`.
  - `RespPending` decides immediately, or waits at most `HANDSHAKE_MS/4` for an in-flight
    GPU-flush read.
  - `RespAcked` waits at most `2×HANDSHAKE_MS` for DONE. The initiator uses an ACK only
    before its own deadline, which is measured from the REQ, so a DONE it sends arrives in
    time unless the socket itself stalls.
  - The ERR drain is bounded by `min(HANDSHAKE_MS/10, 100 ms)`.
- **Symmetric faults.** Both ranks can initiate at once without deadlock. Each proxy thread
  keeps returning from `test()` and so keeps serving its own recv comm, which answers the
  peer.
- **Failure propagation.** A NACK latches both sides. On any other failure, the failing side
  sends FAIL, and the peer latches when it reads it. So neither rank waits for a transfer
  that will never complete.
- **Answering is not capped.** A failed recv comm still NACKs any REQ it receives.
- **When nothing reads the REQ.** If the responder has no outstanding request and posts no
  receive, nobody reads the REQ; the initiator's deadline covers this case.

## 6. Liveness (0x81 sub-cause and gate)

`recv(fd, &c, 1, MSG_PEEK|MSG_DONTWAIT)` on the comm's OOB socket:

| Result | Meaning |
|---|---|
| `0` | FIN: the peer process closed or exited (`proc_kill`) |
| `-1` with ECONNRESET, EPIPE, ETIMEDOUT or ENOTCONN | RST or TCP failure: the peer is gone |
| `-1` with EAGAIN, or bytes pending | no evidence of death (`server_qp_err` or a path problem) |

- The result feeds the `0x81 sub-cause` log line.
- It is also a gate: recovery is initiated only on "no evidence".
- **Limitation:** a host that dies without emitting FIN/RST (power loss, panic, cable pull) is
  not detected here until TCP itself times out. The handshake deadline still bounds the
  attempt.
- In the idle state, a FIN only marks the peer as closed; it does **not** fail the comm.
  Stock does not fail on it either, and failing there could turn a normal teardown race into
  an error.

## 7. Classification (`ncclIbFrClassify`)

| Status (vendor) | Recoverable | Reason |
|---|---|---|
| WR_FLUSH_ERR (0xf5) | yes, if §3 holds | Local QP left RTS without its own completion error |
| REM_ACCESS_ERR (0x88) | no | The NAKing responder QP raises `IBV_EVENT_QP_ACCESS_ERR`. `ncclIbAsyncThreadMain` then calls `ncclIbQpFatalError(qp)`, which increments `stats.fatalErrorCount` on the peer comm (`qp_context` = `&comm->base.stats`). The count is never cleared, and `ncclIbStatsCheckFatalCount` fails every later test/isend/irecv of the peer comm. |
| REM_INV_REQ_ERR (0x8a) | no | Same path, via `IBV_EVENT_QP_REQ_ERR` |
| RNR_RETRY_EXC_ERR (0x87) | no | NCCL uses `rnr_retry=7` (infinite), so this means a broken peer |
| RETRY_EXC_ERR (0x81) | no | No ACK at all (peer QP in ERR, process dead, or path down); see liveness |
| LOC_LEN_ERR, LOC_PROT_ERR | no | A local WR/MR bug that a replay would repeat |
| other | no | |

A software-forced ERR (the inject hook) raises no async event, on either side.

## 8. QP rebuild = connect-time attributes

| Attribute | Rebuilt with |
|---|---|
| INIT: pkey_index, port_num, access flags | Same as `ncclIbCreateQp`. The flags are the ones recorded there (`IBV_ACCESS_REMOTE_WRITE` for data QPs). |
| ECE | Before RTR, `ibv_set_ece` is called again with the same ECE, if connect/accept called it. |
| RTR: dest QPN, remote dev info (GID/LID/MTU/port), `override_tc` | The same values `ncclIbConnect`/`ncclIbAccept` used (`remQpn`, `base->remDevs[remDevIdx]`, `overrideTc` = 1 for recv QP 0). |
| RTR/RTS: timeout, retry_cnt, rnr_retry, rd_atomic | Unchanged. `ncclIbRtrQp`/`ncclIbRtsQp` are reused; the new PSN parameters default to the stock value 0. |
| PSNs | The only difference: fresh random PSNs exchanged in REQ/ACK |

## 9. Known limitations / residual risk

- **Not run on 2-node GPUs yet.** Everything here is the build plus static reasoning;
  `logs/autorun_recovery_test.sh` is the validation.
- **Narrow recoverable class.** In production, WR_FLUSH_ERR as the *first* error with no async
  event mostly comes from software moving the QP to ERR. Real NAK, retry and link faults are
  classified and logged, then fail like stock.
- **Pipelining limits what is recovered.** Recovery happens only when exactly one send and one
  receive are in flight on the connection. With NCCL's default pipelining (several channels,
  up to 8 receives posted ahead), most faults decline cleanly. Stage 2 (replaying several
  outstanding requests) is not implemented.
- **Hot-path cost with the flag on.** A recv comm makes one extra non-blocking `recv()`
  syscall per `ncclIbTest`/`ncclIbIrecv`.
- **Latency cost of a recovery.** The ERR drain is a bounded busy-poll of at most
  `min(HANDSHAKE_MS/10, 100 ms)` on the proxy thread. With the flag on, a send comm also makes
  one non-blocking `recv()` per `ncclIbTest`.
- **Latched ops starve the ops behind them.** A latched comm's op fails on every progress call,
  and `proxy.cc` `progressOps` stops at the first failing op. Ops behind it on that proxy thread
  (including a recv comm that would NACK a peer's REQ) are no longer progressed. The peer then
  fails through its deadline. The communicator is already in error.
- **Provider assumption.** After `modify_qp(RESET)` returns, the device writes no further CQE
  for that QP (true on mlx5). CQEs a provider leaves in the CQ are handled by the post-RESET
  drain. The recovered receive's WQE has already produced its CQE before RESET, so a late CQE
  could only be an error, never a completion.
- **mlx5 (ConnectX-6 Dx) is the target provider.** See the provider assumption above.
- **Stale PSN collision.** The probability that a stale packet of the old incarnation hits the
  new expected PSN is about 2^-24 per such packet.

## 10. Test plan (`logs/autorun_recovery_test.sh`; run on 2026-09-23, results in README)

1. **base:** flag off on both ranks, 1-channel config. Must pass bit-exact with no `[FAULT-`
   lines.
2. **inject:** flag on for both ranks, `NCCL_RDMA_FAULT_INJECT=40` on rank 0, config 1 channel
   / Ring / Simple / 1 QP / 256 KB.
   - Expected: RECOVERED (all iterations bit-exact on both ranks) or DECLINED (clean `rc=3` on
     both ranks, with a NACK/declined reason in the log).
   - Why k=40: it is a multiple of 8, so it lands on the *last* net send of an all-reduce
     whether an op has 2, 4 or 8 net sends per rank. At that point the peer has a single
     receive outstanding.
3. **symmetric:** inject 40 on both ranks. Must not deadlock; RECOVERED or DECLINED as above.
4. **pipelined:** default channels and protocols, 16 MB message, inject 7. Must complete or
   fail cleanly. Never a hang or a mismatch.
5. **prockill:** rank 1 is SIGKILLed mid-run. Rank 0 must fail cleanly (RETRY_EXC after about
   34 s with the default IB timeout); rank 1's FIN alone does not fail it.
