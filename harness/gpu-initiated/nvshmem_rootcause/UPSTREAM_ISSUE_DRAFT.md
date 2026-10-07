<!--
Posted on 2026-10-07 as https://github.com/NVIDIA/nvshmem/issues/117, in the layout of the web form
"NVSHMEM issue or bug". The posted platform field adds the GPUs, CUDA 12.8 and the firmware.
Earlier note: use the web form "NVSHMEM issue or bug" and paste each
section into the field with the same name. Leave "Share Your Debug Logs" empty. Logs
(results/20261001_official380/issue_logs/), the reproducer (official380/kill_repro.cu) and the long
write-up (UPSTREAM_ISSUE_EVIDENCE.md) are for follow-up if asked.
-->

**Title:** [Issue]: IBGDA CPU proxy writes the SQ producer index into the wrong word of the QP doorbell record

### How is this issue impacting you?

Application hang

### Steps to Reproduce the Issue

1. Use `NVSHMEM_IBGDA_NIC_HANDLER=cpu_host_memory` (or `cpu`).
2. Cause any QP error, for example by killing the peer PE during a put + `nvshmem_quiet()` loop.

`nvshmem_quiet()` then does not return: no CQE is ever generated for the failed WQE. With the GPU
handler, or with the fix below, the error CQE is generated and the wait ends once the retries run
out. Reproduced 3/3 on v3.8.0-0 with ConnectX-6.

### NVSHMEM Version

3.8.0 (the same code is in 3.5.x through devel)

### Your platform details

2 nodes, ConnectX-6, RoCE v2

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
