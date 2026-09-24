# GPU-initiated RDMA fault study: combined results (2026-09-23)

Testbed: rain (Quadro RTX 5000, sm_75) and sunny (RTX A4000, sm_86), one ConnectX-6 Dx each
(fw 20.43.4100), RoCE v2, PMTU 4096. Without PeerMappingOverride every GPU-initiated stack runs
in its CPU-doorbell fallback: the GPU writes the WQEs and polls a CQ in GPU memory, and a CPU
thread rings the doorbell. That is how everything except `gpu_doorbell/` ran; `gpu_doorbell/`
reloaded the driver with the override for two short windows so the GPU rang the doorbell itself.
Unless stated otherwise the IB ack timeout is 14. Details, raw data and
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
| NVSHMEM IBGDA (stock, CPU-proxy handler) | no error CQE, no host signal | invalid rkey: QP in ERR but no error CQE | no error CQE (QP reaches ERR) | no error CQE | hangs | `nvshmem_finalize` hangs |
| NVSHMEM IBGDA, GPU handler (PeerMappingOverride) | CQE 5/0xf5, 1.8 ms | CQE 10/0x88, 9 ms | CQE 12/0x81, 3.5-3.7 s | - | quiet **returns success** on a failed put (slot 5/0xf9) | - |
| NVSHMEM IBGDA, CPU proxy + SQ-DBR fix | CQE 5/0xf5 | CQE 10/0x88, 10 ms | CQE 12/0x81, 3.5-3.6 s | - | - | `nvshmem_finalize` still hangs |
| GIN GDAKI + Q4 classifier | 5/0xf5, 15 ms | 10/0x88, 2.8 ms | 12/0x81, 3.64-3.70 s | 12/0x81, 3.64-3.70 s | returns `ncclRemoteError` (silent success 0/9) | clean |
| GIN GDAKI + Q4 + recovery | **recovered**, ~24 ms after the fault | declined (REM_ACCESS) | **recovered**, 3.65-3.74 s after the fault | declined (peer dead) | recovered or declined | clean |

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
   to -EIO and its host sees only "QP in ERR" every 10 s. NVSHMEM IBGDA with its CPU-proxy handler
   never showed an error CQE in any of the 1024 entries of its CQs, even with the requester QP
   confirmed in ERR.
3a. **That NVSHMEM behaviour is a bug in its CPU-proxy handler (`nvshmem_rootcause/`).** The proxy
   writes the send producer index into word 0 of the QP doorbell record (the receive counter)
   instead of word 1; the NIC reloads the producer from the record at the ERR transition, sees an
   empty send queue and writes no completion. CPU reproduction: 0/35 error CQEs with the word at 0,
   21/21 with it written. In NVSHMEM itself, fixing only that word (default-off knob) or using the
   GPU handler (`gpu_doorbell/`) brings REM_ACCESS, RETRY_EXC and WR_FLUSH CQEs back. It affects
   any system that runs IBGDA without PeerMappingOverride.
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

9. **Transient faults can be recovered without losing or duplicating anything (`gin_recovery/`).**
   On GDAKI, with the kernel returning on error, a host-side prepare/handshake/commit and an
   application replay that re-sends the data but only the missing part of the signal, F1 and F3
   recovered in every trial (including several faults per run and a fault during the replay),
   with every iteration's data bit-exact and the final signal exact; F2 and F4 declined cleanly.
   Recovery takes about 8 ms after the kernel returns; detection (F3: retry exhaustion) dominates.
   Two resync details were essential and were proven by negative controls: the CQ mapping
   (`cqe_rsvd`) must advance cumulatively, and the proxy doorbell mailbox must be cleared.

## Rejected or corrected along the way

- "NVSHMEM puts to a failed peer never retire": wire counters showed about 4 s of retransmission
  and then silence, i.e. the NIC did act. Replaced by "no error completion reaches the CQ".
- "QUERY_QP cannot see ERR": a race in the watch thread. QUERY_QP is accurate (F1 and F2b reach
  ERR; F3 stays RTS).
- "Infinite RNR retry explains F3": a peer QP in ERR drops packets silently (harness), no RNR.
- "The collapsed CQ hides error completions": rejected by the in-stack A/B in GDAKI (`gin_q4/`).
  The real cause is the doorbell-record word (finding 3a).
- "F3 leaves NVSHMEM's requester QP in RTS" and "the watch thread raced init": both artifacts of
  a watch thread that held `rc_endpoint_lock` while sleeping and so kept the CPU proxy from ringing
  the failing put. Without it the QP reaches ERR ~3.6 s after the put (`nvshmem_rootcause/`).
  The NVSHMEM `ab/` F1/F3 cells and its `cc=0` "init hangs" ran with that watch and are invalid.
- GIN: surface times were first relative to program start; the ">55 s at IB timeout 20" bound
  came from runs that exited at 4.8 s; "GDAKI's host never learns" came from exiting before the
  10 s check. All re-measured.

## Open questions and next steps

Resolved on 2026-09-24:
1. Why NVSHMEM IBGDA's CQ never receives an error CQE: the CPU proxy's doorbell-record word
   (finding 3a, `nvshmem_rootcause/`).
2. Why F3 left NVSHMEM's requester QP in RTS: it did not; a lock-holding watch thread kept the put
   from being rung.
3. GPU-rung doorbells (`gpu_doorbell/`): NVSHMEM's GPU handler gets the error CQEs; GIN Q4 behaves
   as with CPU doorbells; stock GDAKI's blocking silent success is unchanged.

4. Recovery on top of Q4 (`gin_recovery/`): F1 (local QP ERR) and F3 (peer QP ERR, peer alive)
   recover in every trial, in both wait modes, including runs with several faults and a fault
   that hits the replay itself; data bit-exact and the signal exact in 38/38 recovered runs
   (110 recovery rounds). F2 (REM_ACCESS) and F4 (peer dead: RETRY_EXC with FIN on the OOB
   socket) are declined cleanly and abort returns. The kernel returns `ncclRemoteError`, the
   host runs prepare (pause the proxy, quiesce, ERR), an OOB handshake that reads the receiver's
   signal value V, commit (bilateral reset with fresh PSNs, GPU-side index and CQ-mapping
   resync, stored connect-time attributes), and the application replays the data plus the
   missing signal delta only. Kernel-return to replay-done: 8.0-8.2 ms median, ~6 ms of it
   firmware QP commands. No measurable no-fault overhead.

Still open:
5. DeepEP cannot run here: its internode and low-latency kernels require SM90 (`setup.py` asserts
   for any other arch), and rain's GPU is sm_75, below even the legacy SM80 path.
6. That GDAKI used GPU doorbells in `gpu_doorbell/` is inferred (neither NCCL nor DOCA logs it).
7. Reporting the NVSHMEM doorbell-record bug upstream (needs the user's go-ahead).
