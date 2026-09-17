# Design: true in-tree NCCL RDMA recovery (bilateral QP reset + WR replay)

Supersedes the first patch's unilateral QP re-drive (which left the two ends' PSNs
inconsistent and never replayed the failed WR). All in `src/transport/net_ib.cc`,
NCCL v2.23.4-1, gated by `NCCL_RDMA_FAULT_RECOVERY=1`, default off unchanged.

## Enablers found in the source

- **`ncclIbNetCommBase.sock`** (the OOB TCP socket) stays OPEN for the comm's whole
  life (closed only in ncclIbCloseSend/Recv). It is a live control channel both ends
  hold — no new channel needed.
- **`ncclSocketTryRecv(sock, ptr, size, &closed, /*blocking=*/false)`** = non-blocking
  peek. Lets `ncclIbTest` (already polled continuously by the proxy) check for an
  incoming recovery message without a new thread.
- **`ncclSocketReady(sock,&r)`** = TCP liveness. This is the in-tree version of the
  docs' FIN-vs-RST signal: it distinguishes RETRY_EXC(0x81) `server_qp_err` (socket
  alive) from `proc_kill` (socket closed/RST), with no RDMA counter (per
  `VERIFICATION_0x81.md`, RDMA counters do not split them).
- Data path is **RDMA_WRITE-based** (recv writes a FIFO CTS via `ncclIbPostFifo`;
  send writes data via `ncclIbMultiSend`). RDMA_WRITE is **idempotent** — replaying
  the same bytes to the same remote buffer is safe (unlike SEND).
- `ncclIbRtrQp(qp,gid,dest_qp_num,devInfo,tc)` + `ncclIbRtsQp(qp)` already exist;
  `ncclIbQp.remQpn` (remote QPN) is already retained. `comm->fifoReqs[slot][...]`
  maps a FIFO slot to its request; `ncclIbMultiSend(comm,slot)` re-posts a slot.

## Role assignment (avoids a bilateral-initiate race)

A comm pair is exactly one send comm + one recv comm. Use `base.isSend` as the role:
**the send side is always the recovery INITIATOR, the recv side the RESPONDER.** So even
if both ends flush, only one initiates; no tie-break needed.

## Phase 1 — bilateral PSN-consistent QP reset (correctness core)

Message on `base.sock`:
```
struct ncclIbRecoverMsg { uint32_t magic; int nqps; uint32_t qpn[NCCL_IB_MAX_QPS];
                          uint32_t psn[NCCL_IB_MAX_QPS]; };  // psn[q] = sender's fresh base PSN for qp q
```
Handshake:
1. On a fault CQE in `ncclIbTest`, classify; if `autoRecoverable` and peer is alive
   (`ncclSocketReady`), begin recovery (bounded by `faultRecoveryAttempts`).
2. **Initiator (send side):** for each QP: ERR→RESET→INIT, pick fresh PSN `P_s[q]`.
   `ncclSocketSend` RECOVER_REQ{qpn, P_s}. Then `ncclSocketRecv` RECOVER_ACK{qpn, P_r}.
   For each QP: `ncclIbRtrQp(qp, gid, remQpn, remDevInfo)` with rq_psn = `P_r[q]`,
   then `ncclIbRtsQp` with sq_psn = `P_s[q]`. (ncclIbRtrQp/RtsQp may need a psn arg
   threaded through — currently they set fixed PSNs; add an override.)
3. **Responder (recv side):** its `ncclIbTest` non-blocking-peeks base.sock; on a
   RECOVER_REQ it forces its QP(s) ERR→RESET→INIT, picks fresh `P_r[q]`, RTR with
   rq_psn = initiator's `P_s[q]`, RTS with sq_psn = `P_r[q]`, then `ncclSocketSend`
   RECOVER_ACK{qpn, P_r}.
4. Both QPs are now fresh and mutually PSN-consistent. Verify with the next data WR.

Deliverable of Phase 1 alone: a **correct** bilateral reset (the current patch's gap),
proven by a post-reset data write completing where before it hung.

## Phase 2 — WR replay (make the transfer actually finish)

After reset, the flushed operation is re-posted (idempotent WRITE):
- **Recv side:** re-post the recv WQE(s) for the outstanding request (flushed by the
  reset) and, if the FIFO CTS write faulted, re-run `ncclIbPostFifo` for that slot so
  the sender re-learns the destination.
- **Send side:** re-run `ncclIbMultiSend(comm, slot)` for the outstanding slot to
  re-post the data WRITE(s) + final signal. Map the faulted `wc->wr_id` back to the
  slot/request (NCCL encodes request index in wr_id; see `ncclIbGetRequest`/wr_id use).
- The request's bounded re-poll then observes the fresh completion → `*done=1`.

Idempotency + unchanged remote MR/rkey make replay safe. If anything fails → clean
`ncclRemoteError` (never fabricate a completion).

## Phase 3 — deterministic exercise of the recoverable path

`NCCL_RDMA_FAULT_INJECT=<k>`: on the k-th signaled send completion, force that QP to
ERR **once** (a transient recoverable flush) without killing the peer. This drives
Phase 1+2 deterministically and lets a test assert the collective still completes
(vs the current test, which only injected 0x81 proc-kill = non-recoverable).

## Gating, bounds, safety

- Everything behind `NCCL_RDMA_FAULT_RECOVERY=1`; flag-off path byte-identical.
- Bounds: `faultRecoveryAttempts` per comm, `faultRetries` per request (already present).
- 0x81 with dead socket (`!ncclSocketReady`) ⇒ decline, clean fail (human intervention).
- Any handshake/replay error ⇒ clean `ncclRemoteError`.

## Test plan

1. Build patched NCCL (sm_75+sm_86, CUDA 12.8); baseline all-reduce over RoCE passes,
   flag-off unchanged.
2. `NCCL_RDMA_FAULT_RECOVERY=1 NCCL_RDMA_FAULT_INJECT=50` on the 2-node all-reduce:
   observe the [FAULT-RECOVERY] classify + bilateral-reset + replay logs, and the
   all-reduce **completes with the correct result** (rbuf all-correct), not a hang.
3. Control: proc_kill (0x81, socket dead) still fails cleanly, no hang beyond abort.
