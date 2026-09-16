# GPU×RDMA fault-tolerance: in-tree NCCL IB-transport integration

Integrates the RDMA fault classifier + recovery from `../common/probe.{h,c}`
directly into **NCCL's own IB transport** (`src/transport/net_ib.cc`), not an
external wrapper/daemon. On a failed IB completion NCCL now classifies the fault
(cause / recommended action / peer-liveness / auto-recoverable), logs it, and for
NAK-class (auto-recoverable) faults attempts a QP-level re-drive instead of
immediately failing. Everything is gated behind `NCCL_RDMA_FAULT_RECOVERY=1`;
default (flag off) behavior is byte-for-byte the stock error path.

## NCCL version
- Upstream: github.com/NVIDIA/nccl
- Tag: **v2.23.4-1**, commit `68b542363f9a44cdaac480f51ebe0fc26de96139`
- CUDA 12.8, GENCODE `sm_75` (rain, Quadro RTX 5000) + `sm_86` (sunny, RTX A4000)

## Files here
- `net_ib_fault_recovery.diff` — the patch (single file, +151 lines). Header
  comment lines begin with `#`; strip them before `git apply` (see below), or
  apply with `git apply -p1` after deleting the `#` banner.
- `nccl_ar2.cu` — 2-rank all-reduce test driver (socket-exchanged `ncclUniqueId`,
  no MPI). This is a TEST driver, not part of the NCCL modification.
- `logs/` — baseline run, fault path with the flag ON, and the flag-OFF control.

## Apply + build
```bash
git clone --branch v2.23.4-1 --depth 1 https://github.com/NVIDIA/nccl.git
cd nccl
sed '/^# /d;/^#$/d' /path/to/net_ib_fault_recovery.diff | git apply    # or edit out the # banner
make -j src.build CUDA_HOME=/usr/local/cuda-12.8 \
     NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
```
Baseline build (unpatched) and patched build both completed **rc=0, no warnings**;
the two `static_assert`s guarding `ncclIbNetCommBase` 32-byte alignment pass
(padding was added to keep the struct a 32-byte multiple).

## Integration points (file:line, patched tree)
All in `src/transport/net_ib.cc`:

| What | Location | Note |
|------|----------|------|
| **Failed-completion error return (the hook)** | `ncclIbTest`, the `if (wc->status != IBV_WC_SUCCESS)` block; stock code returned `ncclRemoteError` right after the `WARN`. | Baseline (unpatched v2.23.4-1): the check is at **line 2108**, the `return ncclRemoteError;` at **line 2124**. |
| Classifier + recovery call site (inserted) | patched line **2252** (`if (ncclParamRdmaFaultRecovery())`), between the stock `WARN` and `return ncclRemoteError;` (patched line **2275**) | gated by `ncclParamRdmaFaultRecovery()` |
| `ncclIbClassify()` (port of `classify()`) | patched line **1186** | maps (status, vendor_err) → cause/action/peerAlive/autoRecoverable |
| `ncclIbStatusStr()` | patched line **1171** | self-contained status name (avoids direct libibverbs symbol dep) |
| `ncclIbFaultRecoverQp()` | patched line **1222** | ERR→RESET→INIT→RTR→RTS on the failed device's QPs |
| `NCCL_PARAM(RdmaFaultRecovery,...)` | patched line **1158** | env var `NCCL_RDMA_FAULT_RECOVERY`, default 0 |
| `struct ncclIbQp.remQpn` (added) | struct def, patched line **903** | retains remote QPN so RTR can be redone |
| remQpn captured at connect | send-side, at the `ncclIbRtrQp(...)` call in `ncclIbConnect` | `comm->base.qps[q].remQpn = remQpInfo->qpn;` |
| remQpn captured at accept | recv-side, at the `ncclIbRtrQp(...)` call in `ncclIbAccept` | `qp->remQpn = remMeta.qpInfo[q].qpn;` |
| bounded counters (added) | `ncclIbNetCommBase.faultRecoveryAttempts` (+pad), `ncclIbRequest.faultRetries` | caps: 3 QP re-drives/comm, 3 re-polls/request |

## Fault taxonomy (ported verbatim from `../common/probe.c` classify())
| status | vendor_err | cause | peerAlive | autoRecoverable |
|--------|-----------|-------|-----------|-----------------|
| WR_FLUSH_ERR (5) | 0xf5 | WR flushed (local QP left RTS) | yes | yes |
| REM_INV_REQ_ERR (9) | 0x8a | malformed WR/len/opcode | yes | yes |
| REM_ACCESS_ERR (10) | 0x88 | bad rkey / out-of-bounds | yes | yes |
| RNR_RETRY_EXC_ERR (13) | 0x87 | responder had no recv WQE | yes | yes |
| RETRY_EXC_ERR (12) | 0x81 | no ACK: responder QP ERR / dead / link down | **no** | **no** |

RETRY_EXC(0x81) is classed non-auto-recoverable → the patch logs and falls through
to the stock error (no QP re-drive), matching the harness verdict.

## Run (2 nodes, 1 GPU each, over RoCE)
rank 0 on **rain** (mlx5_1, 30.0.0.3), rank 1 on **sunny** (mlx5_0, 30.0.0.4):
```bash
# rank 0 (rain)
LD_LIBRARY_PATH=nccl/build/lib:/usr/local/cuda-12.8/lib64 \
NCCL_IB_HCA=mlx5_1 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=ens4f1np1 \
NCCL_RDMA_FAULT_RECOVERY=1 NCCL_DEBUG=INFO NCCL_DEBUG_SUBSYS=NET \
./nccl_ar2 0 30.0.0.3 42060 200 1048576 300
# rank 1 (sunny)  -- built binary + libnccl.so + libcudart.so.12 shipped to sunny
LD_LIBRARY_PATH=. NCCL_IB_HCA=mlx5_0 NCCL_IB_GID_INDEX=3 NCCL_SOCKET_IFNAME=enp23s0f0np0 \
./nccl_ar2 1 30.0.0.3 42060 200 1048576 300
```

## Test results
- **Baseline all-reduce over RoCE: PASS.** Both ranks select
  `NET/IB : Using [0]mlx5_1:1/RoCE` (rain) / `mlx5_0` (sunny), GID 3, and every
  iteration returns the correct reduced value (`rbuf[0]=3` for inputs 1+2).
  100/100 and 200/200 iterations completed. (`logs/baseline_rank0.log`)
- **Fault injection (kill peer rank mid-run) with flag ON: classifier fires.**
  Killing rank 1 on sunny mid-run produced, on rank 0:
  ```
  NET/IB: Got completion from peer 30.0.0.4 with status=12 opcode=129 len=524288 vendor err 129 (Recv) ... hca mlx5_1
  NET/IB: [FAULT-RECOVERY] status=12(RETRY_EXC_ERR) vendor_err=0x81
      cause='transport retries exhausted (no ACK): responder QP in ERR, process dead, or link down'
      action='probe peer liveness (control channel / bootstrap TCP; RDMA counters do NOT split the cause); if dead -> human intervention, else QP-only'
      peerAlive=0 autoRecoverable=0
  ```
  Correct classification of the real IB completion error (RETRY_EXC 12 / 0x81),
  correctly declining recovery for a dead peer. (`logs/fault_recovery_ON_rank0.log`)
- **Flag OFF (default): behavior unchanged.** Same kill produces the stock
  `Got completion from peer ... status=12` WARN and **zero** `[FAULT-RECOVERY]`
  lines. (`logs/fault_recovery_OFF_rank0.log`)

## Bounded honesty / blockers (things NOT fully solved in-tree)
1. **Transparent data-plane resume is not achievable purely in-tree, and is not
   faked.** `ncclIbFaultRecoverQp()` genuinely re-drives the local QP
   ERR→RESET→INIT→RTR→RTS (reusing the retained remote QPN, so the local qp_num
   is preserved and the peer still targets us), which leaves the QP object
   usable. It does **not** by itself resume an in-flight RC transfer, because
   (a) the remote QP's PSN is not reset in lockstep, and (b) the failed WR is not
   replayed. NCCL's mid-stream IB path has no bilateral re-handshake channel
   (the socket handshake only runs at connect/accept). So for a persistent fault
   the bounded re-poll (max 3) is exhausted and the comm fails **cleanly** — we
   never mark a transfer complete that did not complete. A full transparent
   recovery would need a new bilateral QP-reset control message added to both
   send and recv comms (a much larger change), or an out-of-tree coordinator.
2. **RETRY_EXC(0x81) sub-cause split is a liveness signal, not an RDMA counter.**
   The verification `../VERIFICATION_0x81.md` measured the responder's fault-window
   RDMA port deltas and found they do NOT distinguish `server_qp_err` from
   `proc_kill`: `port_rcv_packets` ≈ 40–52 for both, `port_xmit_packets` = 0 for
   both. The discriminator is process liveness (the docs use the bootstrap TCP
   sideband FIN-vs-RST). The patch classes RETRY_EXC as `peerAlive=0` /
   `autoRecoverable=0` and defers to that liveness signal; NCCL already carries a
   bootstrap TCP channel whose teardown (FIN vs RST) can be read in-tree, so this
   need not be out-of-tree. (An earlier draft wrongly cited responder
   `port_xmit_packets` as the discriminator — corrected per the verification.)
3. **Test launch is not MPI.** rain has no MPI; sunny has OpenMPI 5.0.10 (HPC-X)
   but **no CUDA toolkit/nvcc and no NCCL**, so `nccl-tests` `all_reduce_perf`
   could not be launched as a 2-node MPI job. Instead the 2-node RoCE all-reduce
   uses `nccl_ar2.cu`, a tiny driver that bootstraps 2 ranks via a socket-exchanged
   `ncclUniqueId` (no MPI). `nccl-tests` itself was still built against this NCCL
   for completeness. This is a *test-harness* substitution only; the NCCL fault
   integration itself is fully in-tree.
4. **Test-driver hang after a fatal fault (not a patch issue).** After the patch
   returns `ncclRemoteError`, NCCL's GPU-side kernel keeps waiting for data unless
   `ncclCommAbort` is called; `nccl_ar2` does not call it, so the process blocks at
   `cudaStreamSynchronize` (killed via `timeout`). This is standard NCCL semantics,
   independent of the patch.

## Reproduce env
rain: mlx5_1 / ens4f1np1 / 30.0.0.3, Quadro RTX 5000 (sm_75), CUDA 12.8, Ubuntu 20.04.
sunny: mlx5_0 / enp23s0f0np0 / 30.0.0.4, RTX A4000 (sm_86), driver 580 (no toolkit).
RoCE v2, GID index 3, 100Gb link. Binary + `libnccl.so.2.23.4` + `libcudart.so.12`
built on rain and shipped to sunny (newer driver is forward-compatible).
