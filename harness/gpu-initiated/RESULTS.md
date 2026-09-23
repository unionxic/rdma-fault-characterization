# GPU-initiated RDMA fault study: combined results (2026-09-23)

Testbed: rain (Quadro RTX 5000, sm_75) and sunny (RTX A4000, sm_86), one ConnectX-6 Dx each
(fw 20.43.4100), RoCE v2, PMTU 4096. No PeerMappingOverride, so every GPU-initiated stack ran in
its CPU-doorbell fallback: the GPU writes the WQEs and polls a CQ in GPU memory, and a CPU thread
rings the doorbell. Unless stated otherwise the IB ack timeout is 14. Details, raw data and
patches are in the four subdirectories; this page only combines them.

| dir | question | what it is |
|---|---|---|
| `cqe_seq/` | Q1 | CPU verbs: the CQE sequence the NIC writes after each fault |
| `gin/` | Q2 | NCCL 2.32.3 GIN, proxy and GDAKI backends, faults F1-F4 |
| `nvshmem/` | Q2, Q3 | NVSHMEM IBGDA (7bb2e99c), faults F1-F4, collapsed-CQ reads |
| `gin_q4/` | A/B, Q4 | GDAKI with a collapsed vs ring CQ; device-side classification + host mailbox |

## What each stack does today when a fault happens

| stack | F1 local ERR | F2 remote access | F3 peer QP ERR | F4 peer killed | blocking wait | teardown after error |
|---|---|---|---|---|---|---|
| CPU verbs (harness) | 5/0xf5, 0.23 ms | 10/0x88, 0.3 ms | 12/0x81, 3.75 s | 12/0x81, 3.73 s | - | - |
| GIN proxy | log 5/0xf5, host 7 ms | log 10/0x88, 3 ms | log 12/0x81, 3.65 s | log **10/0x88**, 60 ms | hangs | abort hangs (blocking comm) |
| GIN GDAKI (stock) | "QP in ERR" only, 9.4 s | same, 10.0 s | same, 9.4 s | same, 8.0 s | **reports the failed write as done** (1 iteration, 9/9) | clean |
| NVSHMEM IBGDA (stock) | no error CQE, no host signal | invalid rkey: QP in ERR but no error CQE | no error CQE, QP stays RTS | no error CQE | hangs | `nvshmem_finalize` hangs |
| GIN GDAKI + Q4 classifier | 5/0xf5, 15 ms | 10/0x88, 2.8 ms | 12/0x81, 3.64-3.70 s | 12/0x81, 3.64-3.70 s | returns `ncclRemoteError` (silent success 0/9) | clean |

Times are from the fault to the first host-visible error. GDAKI's stock times are set by its
10 s QP-state check (`NCCL_GIN_ERROR_QUERY_SEC`), not by the fault.

## Findings

1. **A single-slot collapsed CQ normally ends up holding a flush, not the root cause (Q1,
   measured on CPU, confirmed on a real collapsed CQ in `gin_q4/`).** After the root-cause CQE
   the NIC writes one `WR_FLUSH 5/0xf9` for every WQE posted behind the failing one, signaled
   or not, about 59 µs after the root cause and then every 9.35 µs. The root cause survives in the
   slot only if the failing WQE was the last one outstanding. On GDAKI's collapsed CQ the slot
   held the root cause at poll time and 5/0xf9 500 µs later (18/18).
2. **A classifier must find the root-cause CQE, not the polled one.** In every Q4 trial the CQE
   that the wait polls (the signal WQE behind the put) was the trailing flush 5/0xf9. Reading only
   the polled CQE would have misclassified every fault. On a ring CQ the device scans back from the
   consumer index to the first error CQE.
3. **Where the error is seen decides what can be known.** The CPU-polled GIN proxy has the full
   fingerprint within milliseconds. The GPU-polled stacks drop it: GDAKI's device poll reduces it
   to -EIO and its host sees only "QP in ERR" every 10 s. NVSHMEM IBGDA never showed an error CQE
   in any of the 1024 entries of its CQs, even with the requester QP confirmed in ERR.
4. **Silent failures exist in production paths.** GDAKI's blocking wait reports a failed write as
   done (the -EIO is discarded by a void wait). Out-of-bounds puts that stay inside the registered
   MR (NVSHMEM heap, GIN window rounded to pages) are silent corruption at every layer, because the
   device APIs do not bounds-check and the NIC sees a valid rkey.
5. **Teardown after an error is not reliable.** `nvshmem_finalize` hangs after any QP error; GIN
   proxy's `ncclCommAbort` hangs in blocking mode. GDAKI's teardown returned.
6. **Retry-exhausted detection is slow at the defaults.** At IB timeout 14 the firmware floor
   gives 3.6-3.75 s on every stack. At the NCCL/NVSHMEM default of 20 the GIN proxy reported
   RETRY_EXC 57-59 s after the fault (4 trials), about 1.7 times the 34 s computed from
   4.096 µs × 2^20 × 8.
7. **The same cause can show different fingerprints.** A killed peer gives RETRY_EXC 12/0x81 on
   CPU verbs and on GDAKI, but REM_ACCESS 10/0x88 within 60 ms on the GIN proxy (the target's
   registration apparently goes away before its QP). F3 and F4 give the same 12/0x81 on GDAKI, so
   a liveness signal is still needed to tell them apart, as on CPU.
8. **Device-side classification works and is cheap (Q4).** With a device classifier and a
   host-mapped mailbox, GDAKI's host learns the exact fingerprint 94 µs after the device detects
   it and `ncclCommGetAsyncError` returns it 190 µs later, instead of "QP in ERR" after 9.4-10 s.
   Silent success disappears. With no fault the median put+signal+flush latency rises by at most
   0.1 µs at 4 KiB (about 1%).

## Rejected or corrected along the way

- "NVSHMEM puts to a failed peer never retire": wire counters showed about 4 s of retransmission
  and then silence, i.e. the NIC did act. Replaced by "no error completion reaches the CQ".
- "QUERY_QP cannot see ERR": a race in the watch thread. QUERY_QP is accurate (F1 and F2b reach
  ERR; F3 stays RTS).
- "Infinite RNR retry explains F3": a peer QP in ERR drops packets silently (harness), no RNR.
- "The collapsed CQ hides error completions": rejected by the in-stack A/B in GDAKI (`gin_q4/`).
  Why NVSHMEM's CQ never shows an error CQE is open.
- GIN: surface times were first relative to program start; the ">55 s at IB timeout 20" bound
  came from runs that exited at 4.8 s; "GDAKI's host never learns" came from exiting before the
  10 s check. All re-measured.

## Open questions and next steps

1. Why NVSHMEM IBGDA's CQ never receives an error CQE (diff its QPC/CQC bits against DOCA's, and
   its CPU-proxy doorbell path).
2. Why F3 leaves NVSHMEM's requester QP in RTS after the NIC stops retransmitting.
3. The same experiments with GPU-rung doorbells (needs `PeerMappingOverride=1` and an nvidia
   module reload on both nodes; on rain the desktop and the user's `mooncake_client` would have to
   stop first).
4. Recovery on top of Q4: the mailbox gives the host the fingerprint in about 0.3 ms; a host-side
   QP reset and a GPU-side producer/consumer index resync are the next pieces, and replay must
   handle GIN's signal atomics (a replayed ADD double-counts).
5. Hopper-class GPUs for DeepEP, which requires SM90.
