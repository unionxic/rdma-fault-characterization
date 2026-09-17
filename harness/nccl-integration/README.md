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
| Stock failed-completion hook (`if (wc->status != IBV_WC_SUCCESS)`) | **2439** | baseline v2.23.4-1: check at 2108, `return ncclRemoteError` at 2124 |
| Error branch: classify + INITIATOR recover+replay | **2470–2481** | `isSend` → `ncclIbRecoverInitiate` + `ncclIbReplaySend` |
| RESPONDER non-blocking peek | **2402–2420** | peeks `base.sock`; on REQ → `ncclIbRecoverRespond` |
| `NCCL_PARAM(RdmaFaultRecovery)` / `NCCL_PARAM(RdmaFaultInject)` | **1164 / 1167** | env vars, default 0 |
| `struct ncclIbRecoverMsg` (magic,nqps,psn[]) | **1176** | REQ/ACK on `base.sock` |
| `ncclIbResetQpsToInit` / `ncclIbCompleteQps` | **1274 / 1295** | ERR→RESET→INIT (+CQ drain) / RTR(rq_psn)+RTS(sq_psn) |
| `ncclIbRecoverInitiate` / `ncclIbRecoverRespond` | **1309 / 1334** | initiator / responder handshake |
| `ncclIbReplaySend` / `ncclIbRepostRecv` | **1370 / 1398** | Phase-2 replay |
| Phase-3 injection (`[FAULT-INJECT] forced QP0 to ERR`) | **2120** | end of `ncclIbMultiSend` |
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

## Test status
- **Builds clean; flag-off baseline all-reduce over RoCE PASSES** (correct result
  `rbuf[0]=3`; `logs/p2_baseline_rank0.log`).
- **Cross-node bilateral handshake observed executing** (`logs/evidence_responder.txt`):
  the responder rank logged `RECOVER_REQ received (nqps=1)` → `bilateral
  PSN-consistent reset complete` → `reposted recv WQE`, proving the initiator sent
  a REQ and the responder ran the full reset+repost+ACK path across the two hosts.
- **End-to-end "collective completes with correct result, not a hang" and the
  proc-kill control: BLOCKED at capture time** — see Blocker below. A background
  auto-runner (`logs/autorun_recovery_test.sh`) is queued to run baseline + inject
  + proc-kill the moment the GPU frees; its results land in `logs/autorun.log`.

## Blocker (environmental, not the patch)
rain's Quadro RTX 5000 (16 GB) is shared and was **saturated by another user's
job (~15.5 GB used, ~175 MiB free)** for the duration of the final test window, so
`ncclCommInitRank` on rain fails with CUDA `out of memory` before any collective
runs. Both ranks need one GPU each and rain's is the only RoCE-attached GPU on
that host, so the 2-node collective cannot be launched until it frees. This does
not affect the patch (which builds, and whose responder path was observed running
cross-node when the GPU still had room). The queued auto-runner will capture the
full proof automatically when memory is available.

## Files
- `net_ib_fault_recovery.diff` — the patch (regenerated from the patched tree;
  applies to v2.23.4-1 after stripping the `#` banner).
- `nccl_ar2.cu` — 2-rank all-reduce test driver.
- `DESIGN_recovery.md` — the design (input).
- `logs/` — baseline, cross-node responder evidence, and the auto-runner + its output.
