<!--
Before posting (not part of the issue):
- Use the web form "NVSHMEM issue or bug" (blank issues are disabled). Paste each section below
  into the field with the same name. The form adds the "[Issue]: " prefix and the triage label.
- Attach to "Share Your Debug Logs" the four redacted logs in
  results/20261001_official380/issue_logs/ (hostnames, IPs and GIDs replaced by redact.py).
- In the <details> block, paste official380/kill_repro.cu.
- Searched all 66 issues (open and closed) and all 46 PRs on 2026-10-01: no existing report.
-->

**Title:** [Issue]: IBGDA CPU-proxy NIC handler writes the SQ producer index into the RQ word of the QP doorbell record (since 3.5.x); after a QP error no CQE is generated and nvshmem_quiet() hangs

### How is this issue impacting you?

Application hang

### Share Your Debug Logs

Unmodified v3.8.0-0, `NVSHMEM_DEBUG=INFO NVSHMEM_DEBUG_SUBSYS=ALL`, one log per rank. Hostnames
and IPs replaced. Attached:
- `stock_cpu_host_memory_kill1_t1.pe0.log` and `.pe1.log`: the hang;
- `stock_gpu_kill1_t1.pe0.log`: same run with the GPU NIC handler;
- `fix_cpu_host_memory_kill1_t1.pe0.log`: CPU proxy with the fix below.

PE 0, stock, CPU proxy:

```
ibgda.cpp 5126 NVSHMEM_IBGDA_NIC_HANDLER: cpu_host_memory
ibgda.cpp 5272 NIC buffer will be on GPU memory.
ibgda.cpp 5285 NIC handler will be CPU with host memory backend.
NVSHMEM INFO Successfully initialized the transport: IBGDA. It will be used for device-side APIs over IB.
ibgda.cpp 3150 Creating 1 DCI QPs (shared: 1, exclusive: 0)
ibgda.cpp 3439 Creating 1 RC QPs
...
PE 0 iter 3: put + signal + nvshmem_quiet() returned after 1.1 ms
PE 0 iter 4: put + signal + nvshmem_quiet() returned after 1.1 ms
(PE 1 SIGKILLed here; this line is our note, not in the log)
PE 0 iter 5: nvshmem_quiet() has not returned after 30 s; exiting without nvshmem_finalize
```

The last three lines come from the test program. NVSHMEM itself prints nothing after the QP fails.

The same handler is chosen by default (`auto`) when the UAR cannot be mapped for the GPU. This is
from an earlier run on devel:

```
ibgda.cpp 5468 NVSHMEM_IBGDA_NIC_HANDLER: auto
ibgda.cpp 5627 NIC handler will be CPU with host memory backend.
WARN: cudaHostRegister with IoMemory failed with error=800. We may need to use a fallback path.
```

### Steps to Reproduce the Issue

**Minimal steps**

1. Build NVSHMEM 3.5.x to 3.8.0 with IBGDA. We used the v3.8.0-0 tag archive, unmodified.
2. Run 2 PEs on 2 nodes with `NVSHMEM_IB_ENABLE_IBGDA=1 NVSHMEM_IBGDA_NIC_HANDLER=cpu_host_memory`.
   - `cpu` behaves the same, and so does the default `auto` when the log shows the fallback above.
   - We set `NVSHMEM_IB_TIMEOUT=14` so that retries run out within seconds.
3. PE 0 loops: one kernel per iteration with `nvshmem_putmem_signal_nbi()` to PE 1, then
   `nvshmem_quiet()`. The test program is below; it uses only the public API.
4. SIGKILL PE 1 after a few iterations.
5. **Expected:** the RC QP runs out of retries and goes to ERR, and the NIC writes an error CQE. The
   device poll sees it, so `nvshmem_quiet()` returns after about 3.7 s. This is what the GPU NIC
   handler does.
6. **Actual:** `nvshmem_quiet()` never returns.
   - No CQE is written for the failed WQE, so `ibgda_poll_cq` keeps waiting for it without a
     bound (`ibgda_device.cuh` 524-592).
   - The test program gives up after 30 s.

Results on v3.8.0-0, 3 trials each:

| Library | NIC handler | First iteration after the kill |
|---|---|---|
| v3.8.0-0, unmodified | CPU proxy (`cpu_host_memory`) | **`nvshmem_quiet()` did not return within 30 s (3/3)** |
| v3.8.0-0, unmodified | GPU | returned after 3537-3755 ms (3/3) |
| v3.8.0-0 + the fix below | CPU proxy (`cpu_host_memory`) | returned after 3744-3792 ms (3/3) |

- Without the kill, all 40 iterations return in about 1 ms, both stock and fixed.
- The stock and fixed libraries differ only in `nvshmem_transport_ibgda.so`. Rebuilding the stock
  plugin after reverting the fix gives a bit-identical file.

Other settings used, needed on these nodes for a 256 MiB BAR1 and for IB transport init:

```
NVSHMEM_REMOTE_TRANSPORT=none NVSHMEM_IBGDA_NUM_RC_PER_PE=1 NVSHMEM_IBGDA_RC_MAP_BY=none
NVSHMEM_IBGDA_NUM_DCI=1 NVSHMEM_DISABLE_CUDA_VMM=1 NVSHMEM_CUMEM_GRANULARITY=2097152
NVSHMEM_SYMMETRIC_SIZE=16M NVSHMEM_MAX_TEAMS=4 NVSHMEM_G_BUF_SIZE=262144
NVSHMEM_G_COALESCING_BUF_SIZE=4194304 NVSHMEM_ENABLE_NIC_PE_MAPPING=1
NVSHMEM_HCA_LIST=<hca>:1 NVSHMEM_IB_GID_INDEX=<RoCE v2 IPv4 index> NVSHMEM_IB_ADDR_FAMILY=AF_INET
NVSHMEM_IB_TIMEOUT=14 NVSHMEM_IB_RETRY_CNT=7
```

<details><summary>Test program (kill_repro.cu)</summary>

```cuda
(paste official380/kill_repro.cu)
```

</details>

**Environment details**

See "Your platform details".

**Intermittency**

None. No fault trial got a CQE:
- 3/3 on unmodified v3.8.0-0, where `nvshmem_quiet()` hung;
- 12/12 earlier on devel 7bb2e99, with four kinds of QP error;
- 35/35 in a CPU-only DEVX reproducer.

**Previous success**

v3.4.5-0 writes the correct word (source inspection; we did not run 3.4.5).

### NVSHMEM Version

3.8.0 (v3.8.0-0 tag archive, unmodified, built from source). The affected lines are the same from v3.5.19-1 to devel 7bb2e99.

### Your platform details

- **GPU & network**
  - 2 nodes, each with one GPU and one ConnectX-6 VPI (MT28908, firmware 20.43.4100).
  - RoCE v2, direct link, PMTU 4096.
  - Node 0: Quadro RTX 5000 (sm_75), driver 570.211.01, kernel 5.15, MLNX OFED 23.10.
  - Node 1: RTX A4000 (sm_86), driver 580.178.04, kernel 6.8, MLNX OFED 25.10.
  - CUDA 12.8; `PeerMappingOverride=1` on both nodes.
- **Environment:** bare metal.
- **Scale:** 2 PEs, one per node. Any QP that enters ERR is affected.

### Error Message & Behavior

**First error**

None, and that is the problem. After a QP error, NVSHMEM gets no CQE, logs nothing, and hangs in
`nvshmem_quiet()`.

**Expected vs. actual**

| | Expected (GPU handler, or the fix below) | Actual (stock CPU proxy) |
|---|---|---|
| QP state | ERR | ERR |
| Error CQE | Yes | **None** |
| `nvshmem_quiet()` | Returns after about 3.7 s | **Never returns** |

**Root cause**

`ibgda_rc_progress()` and `ibgda_dci_progress()` in `src/modules/transport/ibgda/ibgda.cpp` write
the SQ producer index into the wrong 4-byte word of the 8-byte QP doorbell record:
- they write **word 0**, the receive counter (`MLX5_RCV_DBR`);
- it should be **word 1**, the send counter (`MLX5_SND_DBR`).

So word 1 stays 0 for the life of the QP.

Normal traffic is unaffected, because the UAR doorbell carries the index. But once the QP is in
ERR, the NIC takes the SQ producer from word 1 of the doorbell record. With 0 there, it believes
nothing was posted and generates no completion: no error CQE and no flush CQEs.

Code in v3.8.0-0, lines 517-518 (DCI) and 581-582 (RC):

```c
dbrec = (__be32 *)((uintptr_t)ep->qp_ctrl.dbr_mobject->aligned.cpu_ptr +
                   ep->qp_ctrl.dbr_offset * sizeof(__be32));
...
ibgda_write_once(dbrec, htobe32(*prod_idx_snapshot & 0xffff));
```

The GPU NIC handler in the same file (3910-3911) and the v3.4.5-0 proxy (475-476) use
`dbr_offset + sizeof(__be32)`. The change came in commit ce9d487 ("ibgda_device: Add
qpair-specific APIs").

`dbr_offset` is a byte offset; it is what `CREATE_QP` receives as `dbr_addr`.
- For RC it is 0, so the proxy writes word 0.
- For DCI k it is `8 * k`, so the proxy writes at byte `32 * k`. That is another DCI's receive word.
  With `NVSHMEM_IBGDA_NUM_DCI > 1`, the write goes past the end of the `8 * num_dcis`-byte buffer.
  This DCI part comes from source inspection only.

rdma-core (`qp->db[MLX5_SND_DBR]` in `providers/mlx5/qp.c`) and the DOCA GPUNetIO CPU proxy
(`dbrec + DOCA_GPUNETIO_IB_MLX5_SND_DBR`) both write word 1.

**More evidence (ConnectX-6)**

The tests below come from our devel 7bb2e99 build, which has a test-only patch. The patch injects
faults and reads the QP, doorbell record and CQ from a separate thread.

1. **NVSHMEM, 2 PEs, put + signal loop.** Four faults were used:
   - invalid rkey;
   - local QP moved to ERR;
   - peer QP moved to ERR, causing retry exhaustion;
   - SIGKILL of the peer.

   Same build and driver state, 53 trials:

   | NIC handler | Error CQE after a fault |
   |---|---|
   | GPU | 16/16 |
   | CPU proxy, stock | **0/12** |
   | CPU proxy, only the doorbell-record word changed | 16/16 |

   No error CQE appeared in any fault-free trial (0/9). With the stock proxy, about 14 s after the
   QP went to ERR:

   ```
   RC qpn=0x5bb9 QUERY_QP ret=0 state=6 hw_sq_wqebb=27 sw_sq_wqebb=0 cur_retry=7
   final RC qpn=0x5bb9 DBR(host) ok=1 word0(rq)=29 word1(sq)=0
   SCAN rc_ncqes=1024 rc_hist{0:1 f:1023 } errs=0
   ```

   - The QP is in ERR (`state=6`).
   - The NIC's SQ producer is 0 (`sw_sq_wqebb=0`).
   - The producer index (29) sits in word 0; word 1 is 0.
   - The CQ holds no error CQE.

2. **CPU-only DEVX reproducer, 57 trials.** One DEVX RC QP + CQ per node, with NVSHMEM's QP/CQ
   attributes and put + signal WQEs. The faults were a local QP error, an invalid rkey, and a peer
   QP in ERR.
   - Word 1 left at 0, as the proxy leaves it: **0/35** error CQEs. All 35 QPs reached ERR.
   - Word 1 written with the producer index: 21/21 error CQEs.
   - The QP's q counter shows the NIC sees the fault either way: `local_ack_timeout_err` +6 or
     `req_remote_access_errors` +1. With word 1 at 0, `req_cqe_error` stays 0.
   - The other 15 differences between NVSHMEM's and DOCA's QP/CQ settings were changed one at a
     time and had no effect.

3. **NIC behavior, 225 trials.** We wrote a chosen value P into word 1 and put the QP into ERR.
   Here c is the first WQE that did not succeed.
   - The NIC wrote exactly one CQE per WQE in `[c, P)`, and none when `P <= c`, in 195/195 trials.
     The `P <= c` case covered 65 of them.
   - In all 225 trials, `QUERY_QP.sw_sq_wqebb_counter` reads P as soon as the QP is in ERR.
   - Raising word 1 later released the missing CQEs within 14-73 µs (30/30).

**Suggested fix**

```diff
--- a/src/modules/transport/ibgda/ibgda.cpp
+++ b/src/modules/transport/ibgda/ibgda.cpp
@@ -515,7 +515,7 @@
                 ep = device->dci.eps[i];
 
                 dbrec = (__be32 *)((uintptr_t)ep->qp_ctrl.dbr_mobject->aligned.cpu_ptr +
-                                   ep->qp_ctrl.dbr_offset * sizeof(__be32));
+                                   ep->qp_ctrl.dbr_offset + sizeof(__be32));
                 bf = (__be64 *)ep->uar_mobject->aligned.cpu_ptr;
 
                 memset((void *)&ctrl_seg, 0, sizeof(ctrl_seg));
@@ -579,7 +579,7 @@
             }
             if (*prod_idx_cache < *prod_idx_snapshot) {
                 dbrec = (__be32 *)((uintptr_t)ep->qp_ctrl.dbr_mobject->aligned.cpu_ptr +
-                                   ep->qp_ctrl.dbr_offset * sizeof(__be32));
+                                   ep->qp_ctrl.dbr_offset + sizeof(__be32));
                 bf = (__be64 *)ep->uar_mobject->aligned.cpu_ptr;
 
                 memset((void *)&ctrl_seg, 0, sizeof(ctrl_seg));
```

With this change, the CPU proxy reports the same errors as the GPU handler (devel build, error CQE
in the slot):

| Fault | CQE (opcode / syndrome / vendor) | When |
|---|---|---|
| Invalid rkey | 0xd / 0x13 / 0x88 | about 10 ms after the put |
| Local QP error | 0xd / 0x05 / 0xf5 | about 2 ms |
| Retry exhausted | 0xd / 0x15 / 0x81 | 3.5-3.8 s at `NVSHMEM_IB_TIMEOUT=14` |
