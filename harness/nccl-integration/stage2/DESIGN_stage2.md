# Design: Stage 2 in-tree NCCL RDMA recovery (many requests in flight)

Target: NCCL v2.23.4-1, `src/transport/net_ib.cc` only. Everything sits behind
`NCCL_RDMA_FAULT_RECOVERY=1` (default 0). Stage 2 replaces the Stage 1 logic
(`../net_ib_fault_recovery.diff`, `../DESIGN_recovery.md`); the Stage 1 files stay as the record
of what was measured on 2026-09-23.

Stage 1 recovers only when exactly one send and one receive are in flight on the connection,
only for a WR_FLUSH first error on the send side. Under NCCL's default pipelining (several
channels, up to 8 receives posted ahead) nearly every fault is declined (measured 2026-09-25:
default config, 16 MB, 3/3 declined). Stage 2 removes those restrictions:

| | Stage 1 | Stage 2 |
|---|---|---|
| requests in flight | 1 send, 1 receive | any number (up to the pool, 256 per comm) |
| who detects | send comm only | either side; the send comm always leads |
| recoverable first errors | WR_FLUSH on the send comm | WR_FLUSH or RETRY_EXC on either comm (peer alive) |
| what is resent | the one failed WRITE_WITH_IMM | every send group the receiver did not get, in FIFO order |
| receive side | re-post the one receive | re-post every outstanding receive, rewrite their CTS entries |
| repeated faults | 3 initiations per comm | rounds until progress, bounded (`MAX_ROUNDS`) |
| silent peer death | not detected until TCP gives up | TCP keepalive on the OOB socket, bounded |
| flag-off footprint | +10.4 KB per comm, request stride 88 → 112 B | one pointer per comm; no stock struct changes |
| flag-on hot path | one `recv()` syscall per recv-comm call | socket polled at most every `POLL_US` (100 µs) |

## 1. Contract

- **Flag off.** The transport makes the same verbs calls with the same arguments as stock.
  Stock structs keep their layout except one pointer (`fr`) in `ncclIbNetCommBase`, which is
  NULL. Every hook is `if (base->fr)` around code that stock does not have. The test-injection
  hooks (§10) are separate knobs and also work with the flag off, so a fault can be driven down
  the stock error path for comparison.
- **Flag on.**
  - Never worse than stock: a recovery either completes with every request completing exactly
    once with the right data, or the comm fails with the stock error (`ncclRemoteError`).
  - Never blocks the proxy thread on a socket, and never makes it wait for the helper thread
    (both use trylock, §8). Every wait has a bound (§5, §7). Verbs calls themselves can block: a
    RoCE `modify_qp(RTR)` resolves the peer's MAC in the kernel (up to about 1 s when the peer
    address is not resolvable), and firmware commands take milliseconds; these are counted in the
    deadlines, not avoided.
  - Never completes a request whose data did not arrive; never drops a valid completion.
  - Transparent to NCCL core: during a recovery `test()` returns not-done and `isend()`/`irecv()`
    return a NULL request (NCCL retries both); nothing above the transport changes.

## 2. The connection model

A connection is one send comm S (rank A) and one recv comm R (rank B), connected by one RC QP
pair (Stage 2 keeps the gate `nqps == 1 && ndevs == 1` on both sides; §12) and one TCP socket
(`base.sock`, opened at connect/accept, unused by stock afterwards). On that QP pair:

- S's SQ carries **send groups**. Group *i* is the send matched to CTS FIFO entry *i*
  (`idx = fifoHead+1` at match time, 1-based, strictly increasing). With `nreqs == 1` and no
  adaptive routing (RoCE: `ar == 0`) a group is one signaled `RDMA_WRITE_WITH_IMM` carrying the
  data and the size as immediate. S's RQ is empty.
- R's RQ carries one receive WQE per posted receive, in `fifoTail` order (the WQE and the CTS of
  a receive are posted in the same `irecv()` call). R's SQ carries **CTS writes**: one
  `RDMA_WRITE` of the FIFO element into S's `fifo[slot]`, signaled only when `slot == 0`
  (stock rule), carrying that receive's request index as `wr_id`.
- R's CQ also receives the completions of the GPU-flush QP (a loopback QP of R). It is not part of
  the connection. When it fails (it uses the same local GID, so an address flap kills it too) it
  is re-driven locally: drain with its own marker, re-resolve the GID, RESET→INIT→RTR(self)→RTS,
  re-post the flush READs still outstanding. No peer is involved.

Invariants used below (all from the stock code):

- **I1** S posts groups in increasing idx; one QP; RC executes them at R in order.
- **I2** R posts receive WQEs in increasing idx; the RQ is consumed in posting order; group *i*'s
  `WRITE_WITH_IMM` consumes exactly one receive WQE, so group *i* completes receive *i*.
- **I3** Therefore the receives that completed form a prefix: there is `R_done` such that
  receive *i* completed iff `i <= R_done`.
- **I4** A send buffer stays reserved until its send request completes; a receive buffer stays
  reserved until its receive request completes. The same bytes can be rewritten to the same
  address, which is what RDMA WRITE replay relies on.
- **I5** At most 256 requests per comm exist at once, so outstanding FIFO indices always span
  fewer than 256 slots: rewriting the CTS entry of an outstanding receive never overwrites a
  newer entry in the same slot.
- **I6** `isend()` consumes FIFO entry `fifoHead+1` only when its `idx` field equals that value,
  and clears `slots[0]` after posting; an entry whose `idx` is not the expected one is ignored.

## 3. Fault classes and triggers

The first error CQE of an incident on the connection QP decides the class (`classify()` is the
Stage 1 table). Recoverable:

| first error | where | meaning |
|---|---|---|
| WR_FLUSH 5 / 0xf5 or 0xf9 | S or R | the local QP left RTS without an error of its own (software ERR) |
| RETRY_EXC 12 / 0x81 | S (data) or R (CTS) | no ACK: the peer QP is in ERR, or the path lost packets long enough |

Recovery of RETRY_EXC additionally needs the peer alive (§7). Everything else (REM_ACCESS,
REM_INV_REQ: the NAKing peer QP raises an async fatal event that NCCL makes permanent;
RNR_RETRY_EXC with `rnr_retry=7`; LOC_LEN/LOC_PROT; an error other than WR_FLUSH/RETRY_EXC on the
GPU-flush QP; any async fatal event on the comm or device) fails the comm like stock.

A trigger can also arrive without a CQE: a **NOTIFY** from the peer (§5), or a posted WR that
fails because the QP is already in ERR (the post succeeds on mlx5 and the WR flushes; this is
how an idle side learns about its own ERR).

## 4. Drain: knowing that a QP has produced every completion

Stage 2 must know, before reconciling, that every WR ever posted to the QP of the old
incarnation has produced its CQE and that the CQE has been consumed. It uses the method of the
kernel's `ib_drain_sq/rq`:

1. `modify_qp(ERR)` (allowed from any state, also from ERR).
2. Post a **marker**: on the SQ a signaled zero-length `RDMA_WRITE` (no SGE) with
   `wr_id = FR_MARK_SQ`; on R also a receive with no SGE and `wr_id = FR_MARK_RQ`. In ERR the
   provider accepts the post and the device flushes it; SQ (RQ) completions are written in
   order, so when the marker's flush CQE is consumed, every earlier WR of that queue has been
   accounted for. If the post fails with ENOMEM (queue full of flushed but unpolled WRs), poll
   and retry.
3. Poll the CQ until the marker(s) are seen, bounded by `NCCL_RDMA_FAULT_DRAIN_MS` (default
   1000; normally microseconds). A timeout fails the comm.

Marker `wr_id`s are values the stock encoding cannot produce (`0xFEFEFEFEFEFEFE01/02`: a stock
send `wr_id` packs up to 8 distinct request indices, a stock receive/CTS `wr_id` is < 256). With
the flag on, every CQE of the comm's CQ passes through `frPoll()` (§8), which recognises markers
and FR-tagged CTS rewrites (§6.4) before the stock decoding.

## 5. Protocol

Channel: `base.sock` (every call `MSG_DONTWAIT`, sends also `MSG_NOSIGNAL`; fixed 56-byte records:
magic, type, epoch, reason, two 64-bit fields, PSN, nqps, ndevs, fingerprint; partial reads/writes
resume on the next call; a TX queue of 8 records). Both sides send **HELLO** once connect/accept
has finished with the socket; a comm whose peer never said HELLO (recovery off there, or not
supported) fails like stock on its first fault instead of waiting for a leader that will never
come.

| message | direction | fields |
|---|---|---|
| NOTIFY | R → S | fingerprint of R's first error |
| REQ | S → R | epoch, `psn_s`, `fifoHead_S`, `nqps`, `ndevs` |
| ACK | R → S | epoch, `psn_r`, `R_done`, `fifoTail_R` |
| NACK | R → S | epoch, reason |
| DONE | S → R | epoch, number of groups replayed |
| FAIL | either | reason |

Roles are fixed: **S leads**. R never resets on its own; if R detects first it drains its QP,
sends NOTIFY and waits for REQ.

```
S (send comm, leader)                                 R (recv comm)
detect (error CQE / NOTIFY / post into ERR)           detect -> drain (§4) -> NOTIFY -> WAIT_REQ
  isend() returns NULL from here on                     irecv() returns NULL from here on
drain SQ (§4)
epoch++ ; psn_s = fresh
REQ{epoch, psn_s, fifoHead_S} ---------------------->  (from IDLE, WAIT_REQ or after DONE)
                                                       drain SQ+RQ (§4) if not already drained
                                                       reconcile (§6.1): R_done, checks
                                                       RESET -> INIT -> [set_ece] -> RTR(rq_psn=psn_s)
                                                             -> RTS(sq_psn=psn_r)
                                                       re-post receives R_done+1 .. fifoTail_R (§6.2)
<------------------------------ ACK{epoch, psn_r, R_done, fifoTail_R}   (or NACK: both fail)
check R_done <= fifoHead_S <= fifoTail_R
reconcile (§6.3): complete groups <= R_done
RESET -> INIT -> [set_ece] -> RTR(rq_psn=psn_r) -> RTS(sq_psn=psn_s)
replay groups R_done+1 .. fifoHead_S in idx order
DONE{epoch, nReplayed} ------------------------------>
isend() allowed again                                  rewrite CTS for fifoHead_S+1 .. fifoTail_R (§6.4)
                                                       irecv() allowed again
```

- R reaches RTR before sending ACK, so S's first replayed packet meets a receive-ready QP.
  S reaches RTR before sending DONE, so R's CTS rewrites meet a receive-ready QP.
- A fault during the replay (or any time later) starts a new round with `epoch+1`; R accepts a
  REQ in any state except FAILED (a REQ while waiting for DONE means S aborted the round and
  starts over; R then drains again).
- **Deadlines.** S waits for ACK at most `HANDSHAKE_MS` (default 5000) + `PATH_WAIT_MS` (default
  30000, R may be waiting for its path, §9) from sending REQ. R waits for DONE at most
  2 × `HANDSHAKE_MS` + `PATH_WAIT_MS` from sending ACK. R in WAIT_REQ waits at most
  `NCCL_RDMA_FAULT_WAITREQ_MS` (default 120000): long, because the leader may be idle, but bounded,
  because a live leader can also be unable to serve the comm (its own comm already failed, or its
  proxy is stuck on another op). Any deadline, NACK, FAIL, FIN/RST during a recovery or a malformed
  record fails the comm on that side and sends FAIL (best effort, `MSG_NOSIGNAL`) so the peer
  fails too. A FAILED comm keeps answering: REQ gets NACK, NOTIFY gets FAIL.
- **Rounds.** S fails the comm after `NCCL_RDMA_FAULT_MAX_ROUNDS` (default 8) consecutive rounds
  without progress (progress = a group completed with a success CQE since the previous round).
  With RETRY_EXC detection of ~3.7 s per round (IB timeout 14) this tolerates a path outage of
  roughly 30 s.
- **Symmetric and concurrent faults.** Each connection recovers independently (its own QP pair and
  socket). Both directions between two ranks are two connections. Each proxy thread keeps
  returning from `test()`, so it keeps serving its other comms; a comm waiting for its peer never
  blocks the peer's leader.

## 6. Reconciliation

### 6.1 R: after its drain

- Every receive request of R is in one of three states: *arrived* (its receive CQE, success,
  was consumed — marked in the side array when `frPoll()` sees `RECV_RDMA_WITH_IMM`), *pending*
  (posted, not arrived), or not a receive.
- By I3, pending receives must be exactly the indices `R_done+1 .. fifoTail_R` with no gap, and
  every arrived receive that is still allocated has `idx <= R_done`. Violation: NACK.
- `R_done = (smallest pending idx) - 1`, or `fifoTail_R` if none is pending.
- Arrived receives whose only remaining event is their signaled CTS completion get `events = 0`
  (the CTS was delivered: S consumed it, since the data arrived).

### 6.2 R: after its reset

- Re-post one receive WQE per pending receive, in idx order, `wr_id` = request index (stock),
  and set each pending receive's `events = 1` (the receive only; any CTS event of the old
  incarnation is dropped, and its rewrite is tracked separately, §6.4).
- R's RQ now holds exactly the pending receives in idx order (I2 holds in the new incarnation).

### 6.3 S: after ACK

- In-flight groups = send requests with outstanding events, grouped by their FIFO idx (side
  array, set in `isend()` at match time). They must form the contiguous range
  `lo .. fifoHead_S` for some `lo`, and no group in `R_done+1 .. fifoHead_S` may be complete
  (a group completes on its success CQE, which implies R executed it, i.e. `idx <= R_done`).
  Violation: fail.
- Groups `<= R_done`: executed at R. Their requests get `events = 0` (complete, size known).
- Groups `R_done+1 .. fifoHead_S`: not executed. After RTS, replay them in idx order with the
  same WR shape as `ncclIbMultiSend` (from the per-idx record of the CTS entry kept at match
  time, because `isend()` clears the FIFO slot), and set their `events = 1`.
- A group whose data was partly written before the fault is rewritten whole: same bytes, same
  address (I4).

### 6.4 R: after DONE — the CTS entries

S's FIFO may lack some CTS entries of receives it has not consumed yet (their writes may have
been flushed on R's SQ). R rewrites the entry of every pending receive with
`idx > fifoHead_S`, from its local copy (`remFifo.elems[slot]`, still intact by I5), in idx
order, as unsignaled `RDMA_WRITE`s with the stock flags, and the last one signaled with an
FR-tagged `wr_id` that `frPoll()` consumes (so the SQ keeps a signaled WR at least every
`MAX_REQUESTS` posts). Rewriting an entry S already holds writes identical bytes (harmless);
rewriting one S consumed meanwhile writes an `idx` S no longer expects (I6: ignored); no newer
entry can be overwritten (I5).

### 6.5 Why every receive completes exactly once, with the right data

- Receive *i* ≤ `R_done`: completed in the old incarnation; S does not resend group *i*.
- Receive *i* in `R_done+1 .. fifoHead_S`: its WQE is re-posted; S replays group *i*; in the new
  incarnation the RQ head and the SQ head are both at `R_done+1`, so group *i* consumes receive
  *i*'s WQE (I1, I2). Same data, same size immediate.
- Receive *i* > `fifoHead_S`: its WQE is re-posted and its CTS entry is present at S (kept or
  rewritten); S matches it later through the normal `isend()` path and sends group *i* for the
  first time.
- A stale packet of the old incarnation cannot be accepted: both QPs were drained in ERR before
  RESET, and the new PSNs are fresh random 24-bit values (a stale packet hits the expected PSN
  with probability about 2^-24).

## 7. Liveness and silent peers

- `recv(MSG_PEEK|MSG_DONTWAIT)` on `base.sock`: 0 = FIN (process exited), ECONNRESET/EPIPE/
  ETIMEDOUT/ENOTCONN = dead; EAGAIN = no evidence. RETRY_EXC is recovered only on "no evidence"
  (the handshake itself then proves the peer's transport is responsive).
- A node that crashes, loses power or is partitioned sends neither FIN nor RST. With the flag on,
  `base.sock` gets TCP keepalive (`SO_KEEPALIVE`, `TCP_KEEPIDLE`/`INTVL`/`CNT`) and
  `TCP_USER_TIMEOUT`, from `NCCL_RDMA_FAULT_KEEPALIVE_MS` (default 5000: idle 2 s, 3 probes 1 s
  apart). The kernel then reports ETIMEDOUT within about that time, which the liveness check
  sees. This bounds R's WAIT_REQ and every handshake wait by peer liveness.
- While IDLE, socket trouble never fails a comm that has nothing outstanding: a FIN (normal
  teardown of the peer) or a keepalive timeout (management network down while RDMA is fine) only
  records that the peer is gone, which disables recovery for that comm; a later fault then fails
  like stock. **But** if send/recv requests are still outstanding when the peer's socket shows
  FIN/RST/timeout, and still after a 50 ms grace in which the CQ is polled, the comm fails: the
  peer process (or node) is gone and will never complete them. This matters when the dead peer was
  the one expected to send: then nothing of ours is in flight, no RETRY_EXC ever comes, and stock
  NCCL waits forever (measured: T8 with back-to-back all-reduces hung 5/5 until the test timeout
  before this rule).
- NCCL calls a comm only while it has an active op, so a leader with nothing pending would never
  read a NOTIFY, and an idle R would never read a REQ. A **helper thread** (one per process, started
  with the first recovery-enabled comm) waits on all their OOB sockets with `poll()` and steps any
  comm that has input or a recovery in progress. The helper and the proxy hooks both take the
  comm's mutex with trylock (the hooks return not-done / a NULL request when they miss it;
  `iflush()` alone waits, because a NULL flush request means "no flush needed" to NCCL).
- The OOB socket should not share the RoCE link (`NCCL_SOCKET_IFNAME` on the management network):
  otherwise a link fault also stops the handshake. With NCCL's default it may use the RoCE netdev;
  the handshake deadline then fails the comm cleanly.

## 8. Hooks in the stock code (flag on only)

- `ncclIbTest`: CQ polling goes through `frPoll()`: markers and FR tags first; success CQEs get
  the stock accounting plus the side-array update (arrived receives); the first error CQE of an
  incident is classified and starts the recovery; later error CQEs during a recovery are
  consumed silently (they are flushes of the old incarnation; their requests are rebuilt in §6).
  `test()` then advances the comm's state machine and returns not-done while a recovery runs.
- `ncclIbIsend`: record `(idx, addr, rkeys, size, request index)` of the matched FIFO entry in
  the per-slot record before the slot is cleared; set the request's side-array idx. Returns NULL
  while S is not IDLE.
- `ncclIbIrecv`: set the request's side-array idx (`fifoTail+1`) and clear its arrived flag;
  returns NULL while R is not IDLE.
- Both, plus `test()`: poll the socket for NOTIFY/REQ/DONE/FAIL, at most every
  `NCCL_RDMA_FAULT_POLL_US` (default 100) using the monotonic clock, and on every call while a
  recovery runs.
- `ncclIbConnect`/`ncclIbAccept`: allocate `fr` when the flag is on; record the connect-time
  attributes (remote QPN, access flags, ECE and whether it was set, `remDevIdx`, `override_tc`);
  set keepalive on `base.sock`.
- `ncclIbCloseSend/Recv`: free `fr`.
- `ncclIbRtrQp`/`ncclIbRtsQp` gain a PSN argument defaulting to the stock 0.

Side allocation (flag on): about 30 KB per comm (256 request entries, 256 send-group records,
socket buffers, state). Stock structs are unchanged apart from the `fr` pointer.

## 9. QP bring-up = connect-time attributes, with the local GID re-resolved

As Stage 1 (`../DESIGN_recovery.md` §8): INIT with the recorded access flags, pkey, port;
`set_ece` again between INIT and RTR if connect/accept set it (`ibv_set_ece` is one-shot: it rides
on the next modify); RTR with the recorded remote QPN and remote device info and `override_tc`
(the recv QP 0 of R uses it); RTS with the stock timeout, retry count, `rnr_retry=7`,
`max_rd_atomic`. The PSNs are fresh.

**The local GID index is looked up again by value** (GID bytes + RoCE version) at every bring-up.
Measured on this testbed (2026-09-25, `gbh_feasibility.sh`): removing a RoCE address for 0.3 s
made the existing QP fail with RETRY_EXC 12/0x81, and the re-added address came back at a new GID
index (5 → 6). The kernel keeps a GID entry that a QP references (pending deletion) but clears
its hardware entry at once, so the re-created address gets another slot while the old QP's
address vector still names the dead one: without recovery, even a sub-second address flap breaks
existing RoCE QPs for good. If the GID is absent, or `modify_qp(RTR)` cannot resolve the peer,
bring-up returns "not ready" and is retried every 20 ms until `PATH_WAIT_MS`.

## 10. Test hooks (knobs independent of the recovery flag)

| knob | effect |
|---|---|
| `NCCL_RDMA_FAULT_INJECT=k` | S side: before the k-th multi-send of the process, force that comm's QP to ERR |
| `NCCL_RDMA_FAULT_INJECT_REPEAT=n`, `..._PERIOD=p` | inject at k, k+p, ..., n times |
| `NCCL_RDMA_FAULT_INJECT_RECV=k` | R side: before the k-th receive post, force the recv QP to ERR |
| `NCCL_RDMA_FAULT_INJECT_RECV_SILENT=1` | instead of at a post, R's QP is forced to ERR right after its k-th receive completion (while S streams the next groups) and R does not NOTIFY: S meets RETRY_EXC. Needs the recovery flag on (it lives in the recovery CQ path) |
| `NCCL_RDMA_FAULT_TEST_MUTE=1` | R never answers REQ (a live but unresponsive peer): S must fail at its deadline |

Faults not made by a hook: SIGKILL of a rank (process death, FIN), and a **GID blackhole**: the
QPs of the test use a RoCE GID of a secondary IPv4 address on the RoCE netdev of each node;
removing that address on one node for T seconds removes the GID, so the NIC drops the
connection's packets (a real path fault: no QP changes state, no software on either rank sees
anything until retries run out); re-adding it restores the path. The storage traffic on the same
link uses the primary addresses and is not affected. (A real link down stays out: the link
carries the user's NVMe-oF.)

## 11. Test plan

All on 2 nodes, NCCL_SOCKET_IFNAME on the management network, IB timeout 14 unless stated.
Correctness in every run: every iteration's whole result buffer bit-exact on both ranks.

| id | case | expected | N |
|---|---|---|---|
| T0 | flag off vs stock, fault-free, 4 sizes × 2 configs | identical results, same latency | 3 reps |
| T1 | S inject, single config, k not aligned to an all-reduce boundary | recovered | 30 |
| T2 | S inject, default config (multi-channel pipelining), 16 MB | recovered | 30 |
| T3 | R inject (R detects, NOTIFY path), default config | recovered | 30 |
| T4 | R inject silent (S sees RETRY_EXC ~3.7 s later) | recovered | 10 |
| T5 | repeated S injections (5 per run) | recovered 5× | 10 |
| T6 | symmetric S injections on both ranks | recovered, no deadlock | 10 |
| T7 | GID blackhole of 0.2 s, 2 s, 10 s | 0.2 s masked by HW retransmission; 2 s and 10 s: RETRY_EXC then recovered after the path returns | 10 each |
| T8 | SIGKILL of rank 1 | rank 0 fails cleanly (FIN) | 10 |
| T9 | mute peer | rank 0 fails at the handshake deadline | 5 |
| T10 | completion time (`../perf`): baseline / recover / restart, single and default | | 5 reps |
| T11 | fault-free overhead with the flag on | ≤ 1–2 % at 64 KB | 3 reps |

This is the plan as written before the runs. What was run, with the N actually used (T7: 5 per outage
length, 0.5 s / 6 s / 15 s, plus stock controls), is in `README.md`; §15 says why T4 changed.

## 12. Limitations (by design)

- Same QPN across incarnations. A stale request packet of the old incarnation that lands exactly on
  the new expected PSN (probability about 2^-24 per packet) would be executed; a stale ACK is
  accepted if its PSN falls in the outstanding window (probability about W/2^24 for a window of W
  packets). Stale packets exist only if the fabric holds them longer than the drain + handshake
  (milliseconds); on the direct link this is not expected, and the hardware counters
  `duplicate_request`, `out_of_sequence`, `packet_seq_err` are recorded around every test to
  check it. A fresh QP per incarnation would remove the risk; not done.

- `nqps == 1 && ndevs == 1` (one QP, one NIC per connection; the default on this testbed). Multi-QP
  splits one group over several QPs whose completions interleave; multi-NIC adds per-device
  FIFOs. Both are declined.
- `nreqs > 1` groups (multi-receive) are declined: their sizes travel in a separate FIFO write.
- Adaptive routing (`ar`, InfiniBand only) splits a group into two WRs; declined if seen.
- The GPU-flush QP is recovered locally (§2) only for WR_FLUSH / RETRY_EXC errors.
- NCCL 2.23's `ncclCommAbort` still hangs after a failed comm (fixed in NCCL 2.26); Stage 2 only
  reduces how often a comm fails.
- A peer that is alive but whose proxy thread never polls the comm can only be detected by the
  deadlines.


## 13. Design QA, round 1 (2026-09-25): findings and what changed

Two independent reviews (protocol/NCCL integration; verbs/mlx5), plus one hardware check.

| finding | severity | resolution |
|---|---|---|
| Replay WR must use the clipped send size and the recorded remote addr/rkey, not MultiSend's offset logic or the (cleared) FIFO slot | major | dedicated replay builder: `sge = {send.data, send.size, lkey}`, `imm = send.size`, record keeps addr/rkey; inject counts first-time multi-sends only |
| Error CQEs dropped silently during a recovery could hide a NAK-class error or a GPU-flush error | major | an error on the GPU-flush QP fails the comm (later changed: WR_FLUSH/RETRY_EXC on it are re-driven locally, §2); a non-recoverable class seen during the drain fails the comm; an error after the new incarnation is up starts a new incident |
| R's WAIT_REQ unbounded while a live leader cannot serve it | major | `WAITREQ_MS` bound; the async-fatal check sends FAIL before the stock check fails the call; a FAILED comm answers REQ/NOTIFY |
| A comm with no active op is never called by NCCL, so the leader or R may never see the peer's message | major | helper thread with trylock on both sides (§7) |
| Socket errors while IDLE (teardown FIN, management-network blip) must not fail healthy comms | major | while IDLE they only disable recovery for the comm (§7) |
| GID removal is not a transparent blackhole: the re-added address gets a new GID index | high (test validity) | measured; bring-up re-resolves the GID by value and waits for the path (§9); T7 expectations changed (no masking; stock QPs die) |
| R's `base.sock` is a blocking fd | minor | every call uses `MSG_DONTWAIT` (+`MSG_NOSIGNAL` for send) |
| SQ margin after the CTS rewrite burst is exactly 512 | low | the rewrite of slot 0 is signaled too (FR tag) |
| CQ capacity for a full flush | low | recovery is enabled only if the CQ holds ≥ 3×256+8 entries (mlx5 rounds 512 up to 1024 here) |
| T4 can hang if R dies while S has nothing in flight | minor (test) | the silent injection fires right after a receive completion, while S streams the next groups |
| RTR can block ~1 s on address resolution; drains take ms with full queues | medium | documented in §1; counted in the deadlines |
| Stale-packet argument incomplete (same QPN) | medium | §12 corrected; counters recorded around tests |
| Responder-side NAK errors surface as async events, not CQEs, on R | medium | the fatal check runs on every step of a recovery before NOTIFY/ACK/DONE |


## 14. Code QA, round 2 (2026-09-25): findings on the implementation and what changed

An independent code review of the patch (plus a local `-Wall -Wextra` build and struct-size check:
the stock structs keep their sizes, `fr` sits in existing tail padding) and the first cluster smoke.

| finding | severity | resolution |
|---|---|---|
| The helper thread could read the 4-byte `ready` of the connect/accept handshake from `base.sock`, and NCCL's lazy connect then hung (the first smoke hung exactly there: "comm ready", then no iteration) | critical | the comm is registered with the helper only when connect/accept returns it (`fr2Activate`), which also sends HELLO |
| `fr` stayed registered on the connect/accept `fail:` paths (helper would touch freed memory) | major | detach before `free()` on both paths |
| Close destroyed socket, QPs and CQ before detaching `fr` | major | detach first in both close functions |
| Errors from `fr2Step` in the helper were dropped | minor | they fail the comm |
| A FAILED comm with `flState≠0` kept the helper busy | minor | `fr2Fail` clears `flState` |
| Helper poll array capped at 64 comms | minor | dynamic |
| A NOTIFY for a fresh fault that arrives mid-round was dropped; NOTIFY had no epoch semantics | minor | NOTIFY carries R's last accepted epoch: older = the incident S is handling (ignored), equal/newer while S is busy = latched and started when S is IDLE |
| Rounds ignored groups completed by reconciliation | minor | counted as progress |
| GID re-resolution required `NCCL_IB_ROCE_VERSION_NUM` rather than the connect-time entry's version | minor | the version of the connect-time entry is recorded |
| `fr2Fatal` ignored `NCCL_IB_RETURN_ASYNC_EVENTS=0` | minor | same switch as stock |
| Asymmetric enablement made a fault wait for a deadline | minor | HELLO |
| Helper held the global list lock while stepping (RTR can take ~1 s) | minor | comms are picked under the list lock and served outside it (detach unregisters, then waits for the comm lock) |
| RTR retries every 20 ms printed a WARN each | minor | backoff 20 ms doubling to 1 s |
| BRINGUP states did not poll the CQ (GPU-flush completions stalled) | minor | they poll |
| Doc drift (message size, TX queue, flush-QP handling, SILENT needing the flag, dead fall-through) | nit | fixed here and in the code |


## 15. What the tests taught (2026-09-25)

- **A silent responder death is only visible to a sender that sends.** With a 2-rank ring
  all-reduce the sender's next group depends on data coming back from the dead side, so when R's
  QP dies right after an iteration S has nothing in flight and waits for a CTS that never comes; no
  RETRY_EXC ever appears (T4 on all-reduce: 5/5 stuck until the test timeout). Only R's own
  detection (NOTIFY, the normal case: T3/T3s) or R's WAITREQ bound ends it. The RETRY_EXC-led path
  was then tried with a one-way broadcast stream (256 KB and 64 MB), but the broadcast is so fast
  that by the time R processes a completion S has usually sent everything it had CTS for, so the
  silent death again leaves S idle (0/13 runs produced a RETRY_EXC at S). The RETRY_EXC-led path is
  instead covered by a REAL path fault (T7, the address flap): there both sides' NICs exhaust their
  retries and S's send comm starts the recovery from its own RETRY_EXC CQE (15/15 recovered). The
  all-reduce silent case is kept as a test of the WAITREQ bound (T4ar: both sides fail cleanly at
  120 s).
- **Peer process death while we wait to receive** had the same shape (T8): fixed by the FIN rule in §7.
