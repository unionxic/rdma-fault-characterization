# GPU×RDMA fault tolerance: in-tree NCCL IB-transport recovery

Integrates RDMA fault classification **and true bilateral QP recovery** directly
into NCCL's own IB transport (`src/transport/net_ib.cc`) — not an external wrapper.
On a failed IB completion NCCL classifies the fault, and for recoverable
(NAK/flush-class) faults performs a **PSN-consistent bilateral QP reset over the
existing OOB socket plus an idempotent WRITE replay**, so the collective can
continue instead of hanging. Everything is gated behind `NCCL_RDMA_FAULT_RECOVERY=1`;
with the flag off the code path is byte-identical to stock NCCL.

This supersedes the first patch's *unilateral* QP re-drive (which left the two
ends' PSNs inconsistent and never replayed the flushed WR). See
`DESIGN_recovery.md` for the design this implements.

## NCCL version
- Upstream github.com/NVIDIA/nccl, tag **v2.23.4-1**, commit `68b542363f9a44cdaac480f51ebe0fc26de96139`.
- CUDA 12.8, GENCODE `sm_75` (rain, Quadro RTX 5000) + `sm_86` (sunny, RTX A4000).
- Build: `make -j src.build CUDA_HOME=/usr/local/cuda-12.8 NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"` → **rc=0, no warnings**, alignment `static_assert`s pass.

## What the patch does (three phases)

**Phase 1 — bilateral PSN-consistent QP reset (correctness core).** Role is fixed
by `base.isSend`: the **send comm is the INITIATOR, the recv comm the RESPONDER**
(a comm pair never double-initiates). The control channel is the always-open OOB
`ncclIbNetCommBase.sock`; no new channel. A fresh per-QP PSN is exchanged so both
ends end up mutually consistent:
- Initiator: on a recoverable fault CQE, ERR→RESET→INIT all QPs (picking fresh
  `P_s[q]`), `ncclSocketSend` RECOVER_REQ{P_s}, `ncclSocketRecv` RECOVER_ACK{P_r},
  then RTR(rq_psn=`P_r`)/RTS(sq_psn=`P_s`).
- Responder: its `ncclIbTest` non-blocking-**peeks** `base.sock` every poll (a
  transient sender-only flush yields NO local error CQE); on a RECOVER_REQ it
  ERR→RESET→INIT (fresh `P_r`), RTR(rq_psn=`P_s`)/RTS(sq_psn=`P_r`), re-posts its
  recv WQE, then `ncclSocketSend` RECOVER_ACK{P_r}. Recv WQE is re-posted **before**
  the ACK so the replayed WRITE never races ahead of a posted receive (no RNR).

**Phase 2 — WR replay (transfer actually finishes).** The data path is
RDMA_WRITE, which is idempotent. At `ncclIbIsend` the remote CTS (addr+rkey) is
snapshotted into the request (the FIFO slot is cleared right after the first
send). After the reset, the initiator re-posts a signaled `RDMA_WRITE_WITH_IMM`
of the full buffer (`ncclIbReplaySend`) and the responder re-posts its recv WQE
(`ncclIbRepostRecv`); event counts are reset to exactly what the replay produces,
and the CQs are drained of stale FLUSH_ERR CQEs first. The request's bounded
re-poll then observes the fresh completion → done. Replay covers the single-request
(`nreqs==1`, single-QP) path (the all-reduce case); multi-recv coalescing and
multi-QP striping replay are out of scope (declines → clean fail).

**Phase 3 — deterministic exercise.** `NCCL_RDMA_FAULT_INJECT=k` forces the send
QP to ERR exactly once, on the k-th signaled multi-send, so its in-flight WRITE
flushes (WR_FLUSH_ERR) while the peer stays alive — a transient RECOVERABLE fault
that drives Phase 1+2 deterministically.

## Safety / gating / bounds
- All behind `NCCL_RDMA_FAULT_RECOVERY=1`; flag-off path byte-identical.
- Bounds: `faultRecoveryAttempts` per comm (max 3), `faultRetries` per request (max 8).
- Any handshake or replay failure → clean `ncclRemoteError` (never fabricate a completion).
- **Dead peer:** RETRY_EXC(0x81) with a dead socket is declined (classifier
  `autoRecoverable=0`); even if a recoverable class saw a dead peer, the blocking
  handshake (`ncclSocketSend/Recv`) fails on the closed socket → clean fail. TCP
  liveness (`ncclSocketReady`) is logged as the in-tree 0x81 `server_qp_err` vs
  `proc_kill` discriminator (RDMA counters do not split them).

## Integration points (file:line, patched tree)
All in `src/transport/net_ib.cc`:

| Element | Line | Note |
|---|---|---|
| Stock failed-completion hook (`if (wc->status != IBV_WC_SUCCESS)`) | **2440** | baseline v2.23.4-1: check at 2108, `return ncclRemoteError` at 2124 |
| Error branch: classify + INITIATOR/RESPONDER recover | **2472–2494** | `isSend` → `ncclIbRecoverInitiate` + `ncclIbReplaySend` |
| RESPONDER non-blocking peek | **2403–2424** | peeks `base.sock`; on REQ → `ncclIbRecoverRespond` |
| `NCCL_PARAM(RdmaFaultRecovery)` / `NCCL_PARAM(RdmaFaultInject)` | **1164 / 1167** | env vars, default 0 |
| `struct ncclIbRecoverMsg` (magic,nqps,psn[]) | **1176** | REQ/ACK on `base.sock` |
| `ncclIbResetQpsToInit` / `ncclIbCompleteQps` | **1274 / 1295** | ERR→RESET→INIT (+CQ drain) / RTR(rq_psn)+RTS(sq_psn) |
| `ncclIbRecoverInitiate` / `ncclIbRecoverRespond` | **1309 / 1334** | initiator / responder handshake |
| Responder 0x81 (peer-resetting) handling | **2479-2485** | live socket → wait for REQ; dead → decline |
| `ncclIbReplaySend` / `ncclIbRepostRecv` | **1370 / 1398** | Phase-2 replay |
| Phase-3 injection (`[FAULT-INJECT] forced QP0 to ERR before post`) | **2019** | top of `ncclIbMultiSend` |
| `ncclIbRtrQp` / `ncclIbRtsQp` PSN override param | **1077 / 1126** | added `rq_psn` / `sq_psn`; 4 prod call sites pass 0 |
| `ncclIbQp.remQpn` (retained remote QPN) | **916** | captured at connect/accept |
| `ncclIbRequest.send.{remoteAddr,rkeys,recoverable}` | **877** | replay snapshot |

## Run (2 nodes, 1 GPU each, over RoCE)
rank0 on rain (mlx5_1/30.0.0.3), rank1 on sunny (mlx5_0/30.0.0.4). Test driver
`nccl_ar2.cu` (socket-exchanged `ncclUniqueId`, no MPI):
```bash
# rank 0 (rain) — INITIATOR side, injects a recoverable flush on the 50th send
LD_LIBRARY_PATH=nccl/build/lib:/usr/local/cuda-12.8/lib64 \
NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=ens4f1np1 \
NCCL_RDMA_FAULT_RECOVERY=1 NCCL_RDMA_FAULT_INJECT=50 \
NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=NET \
./nccl_ar2 0 30.0.0.3 43110 60 1048576 150
# rank 1 (sunny) — RESPONDER; recovery flag on, no inject
LD_LIBRARY_PATH=. NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=enp23s0f0np0 \
NCCL_RDMA_FAULT_RECOVERY=1 ./nccl_ar2 1 30.0.0.3 43110 60 1048576 150
```

## Test status — all phases verified end-to-end over 2-node RoCE

Config for the fault runs: `NCCL_MAX_NCHANNELS=1 NCCL_PROTO=Simple NCCL_BUFFSIZE=8388608`,
512 KB message (131072 floats) so exactly one net WRITE is in flight per step (see
Scope below). rank0=rain(mlx5_1), rank1=sunny(mlx5_0), GID 3.

1. **Build clean; flag-off baseline all-reduce PASSES** (correct result; `logs/p2_baseline_rank0.log`).
2. **Phase 1+2+3 — injected recoverable flush, collective COMPLETES with correct
   result (not a hang):** `NCCL_RDMA_FAULT_RECOVERY=1 NCCL_RDMA_FAULT_INJECT=20`.
   rank0 exit=0, **40/40 iters, `[rank0] done`, every `rbuf[0]=3`.** The recovery
   sequence (`logs/phase123_inject_rank0.log` / `_rank1.log`):
   - rank0 (INITIATOR): `[FAULT-INJECT] forced QP0 to ERR before send #20` →
     `status=5(WR_FLUSH_ERR) ... role=INITIATOR sockAlive=1` →
     `initiator: bilateral PSN-consistent reset complete` →
     `replayed WRITE_WITH_IMM size=131072 -> remoteAddr=... rkey=...` →
     `recovered + replayed (attempt 1/3); resuming` → **all 40 iters complete.**
   - rank1 (RESPONDER): `RECOVER_REQ received (nqps=1)` → `reposted recv WQE` →
     `bilateral PSN-consistent reset + recv repost + ACK done`.
   This is the correctness core: both ends reset to mutually-consistent fresh PSNs
   over `base.sock`, the flushed WRITE is replayed, and the transfer + collective
   finish correctly — exactly what the unilateral first patch could not do.
3. **Control — proc-kill (dead peer) still fails cleanly:** `NCCL_RDMA_FAULT_RECOVERY=1`,
   rank1 killed mid-run. rank0 detects the dead peer (`responder peek: peer socket
   closed` → `ncclRemoteError`), **declines recovery, does not loop or fabricate a
   completion** (`logs/control_prockill_rank0.log`). (The process then blocks until
   `timeout` because the test driver never calls `ncclCommAbort` to tear down the
   waiting GPU kernel — standard NCCL semantics, independent of the patch.)
4. **Flag-off default byte-identical:** with the flag off the same kill yields the
   stock `Got completion ... status=12` WARN and zero `[FAULT-RECOVERY]` lines.

## Scope / limitations (honest)
- **Single in-flight request per comm.** NCCL pipelines several net WRITEs at once;
  forcing a QP to ERR flushes *all* of them, but the recovery replays only the one
  request under test and drains the CQ of the rest. The verified runs therefore use
  1 channel + Simple proto + a single-chunk (512 KB) message so exactly one WRITE is
  outstanding. With default multi-channel/pipelined settings the reset+replay still
  execute (observed), but un-replayed sibling requests then stall the collective.
  General multi-request replay (tracking every flushed request per comm) is future work.
- **Injection point:** `NCCL_RDMA_FAULT_INJECT=k` forces the QP to ERR *before* the
  k-th multi-send's post (net_ib.cc:2019), so the WRITE deterministically flushes
  regardless of size. (Forcing ERR *after* the post let small/fast sends complete
  first, so no recoverable flush was produced — that variant was dropped.)
- **Bidirectional QP pair:** a QP pair carries both the initiator's data WRITEs and
  the responder's CTS WRITEs, so an initiator-side ERR makes the responder's recv
  comm see RETRY_EXC(0x81) on its CTS path even though the peer is alive. The patch
  handles this: on the RESPONDER, 0x81 **with a live socket** is treated as
  "peer is resetting" → wait for the REQ (net_ib.cc:2479-2485); 0x81 with a dead
  socket is declined. This is what lets the collective survive the injected fault.

## Blocker encountered (now cleared)
For part of the session rain's shared Quadro RTX 5000 was saturated by another
user's ~15.5 GB job (~175 MiB free), so `ncclCommInitRank` failed with CUDA OOM and
the fault runs could not launch. It later freed and all runs above were captured.

## Files
- `net_ib_fault_recovery.diff` — the patch (391 insertions; applies to v2.23.4-1 after stripping the `#` banner).
- `nccl_ar2.cu` — 2-rank all-reduce test driver (socket-exchanged uniqueId, no MPI).
- `DESIGN_recovery.md` — the design (input).
- `logs/phase123_inject_rank0.log`, `_rank1.log` — the successful recovery + completion.
- `logs/control_prockill_rank0.log` — dead-peer clean decline.
- `logs/p2_baseline_rank0.log`, `evidence_responder.txt`, `autorun_recovery_test.sh`.
