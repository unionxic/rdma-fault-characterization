<!--
Posted on 2026-10-07 09:10 KST as https://github.com/NVIDIA/nvshmem/issues/117, in the layout of the web
form "NVSHMEM issue or bug". The body was edited once, on 2026-10-07 10:31 KST, before any reply:
"Share Your Debug Logs" (posted empty) got a log excerpt from ../cq380/results/20261007/, and
"Steps to Reproduce" got one paragraph with the direct CQ read of ../cq380/. Below is the body as it
stands after that edit, copied from GitHub. The longer write-up is UPSTREAM_ISSUE_EVIDENCE.md; the
reproducer and the full logs are for follow-up if asked. The issue does not link this repository.
Closed by the maintainer on 2026-10-08 05:13 KST as completed: "Fixed internally, closing and the fix will
pop out next time we sync."
-->

**Title:** [Issue]: IBGDA CPU proxy writes the SQ producer index into the wrong word of the QP doorbell record

### How is this issue impacting you?

Application hang

### Share Your Debug Logs

v3.8.0-0, NVSHMEM_DEBUG=INFO. PE 1 is killed with SIGKILL after iteration 3.

With NVSHMEM_IBGDA_NIC_HANDLER=cpu_host_memory:

```
./src/modules/transport/ibgda/ibgda.cpp 5285 NIC handler will be CPU with host memory backend.
PE 0 iter 3: put + signal + nvshmem_quiet() returned after 1.1 ms
PE 0 iter 4: put + signal + nvshmem_quiet() returned after 1.1 ms
PE 0 iter 5: nvshmem_quiet() has not returned after 30 s; exiting without nvshmem_finalize
```

A separate run with NVSHMEM_IBGDA_NIC_HANDLER=gpu:

```
./src/modules/transport/ibgda/ibgda.cpp 5287 NIC handler will be GPU.
PE 0 iter 5: put + signal + nvshmem_quiet() returned after 3535.9 ms
```

Here "returned" only means the wait ended, after the retries ran out.

### Steps to Reproduce the Issue

1. Use `NVSHMEM_IBGDA_NIC_HANDLER=cpu_host_memory` (or `cpu`).
2. Cause any QP error, for example by killing the peer PE during a put + `nvshmem_quiet()` loop.

`nvshmem_quiet()` then does not return: no CQE is ever generated for the failed WQE. With the GPU
handler, or with the fix below, the error CQE is generated and the wait ends once the retries run
out. Reproduced 3/3 on v3.8.0-0 with ConnectX-6.

We also read the CQ buffers directly on v3.8.0-0 (5 trials per case, peer killed). With
cpu_host_memory, while nvshmem_quiet() was stuck, neither the DCI nor the RC CQ held an error
CQE; the only CQE in each was a success. With the GPU handler, and with cpu_host_memory plus the
fix below, the RC CQ held an error CQE in 5/5 trials (syndrome 0x05, vendor syndrome 0xf9).
Without a fault, no case produced an error CQE.

### NVSHMEM Version

3.8.0 (v3.8.0-0, CUDA 12.8); the same code is in 3.5.x through devel

### Your platform details

Bare metal, 2 nodes with one PE each, ConnectX-6 (fw 20.43.4100), RoCE v2, Quadro RTX 5000 and RTX A4000

### Error Message & Behavior

`ibgda_dci_progress()` and `ibgda_rc_progress()` in `src/modules/transport/ibgda/ibgda.cpp`
compute the doorbell record address as

```c
ep->qp_ctrl.dbr_offset * sizeof(__be32)
```

It should be `dbr_offset + sizeof(__be32)`, which is word 1, the SQ counter. That is what the GPU
handler in the same file and v3.4.5 use; it became `*` in ce9d487.

As a result, the proxy writes the SQ index into word 0 (the RQ counter), and word 1 stays 0.
- **Normal traffic** still works, because the UAR doorbell carries the index.
- **After a QP error**, no CQE is generated, not even the error CQE, so `nvshmem_quiet()` hangs.
- **For DCIs** (`dbr_offset = 8 * k`), the write lands at byte `32 * k`. That is another DCI's
  record, or past the end of the buffer.

```diff
@@ ibgda_dci_progress
-                                   ep->qp_ctrl.dbr_offset * sizeof(__be32));
+                                   ep->qp_ctrl.dbr_offset + sizeof(__be32));
@@ ibgda_rc_progress
-                                   ep->qp_ctrl.dbr_offset * sizeof(__be32));
+                                   ep->qp_ctrl.dbr_offset + sizeof(__be32));
```

We can share logs and a reproducer.

