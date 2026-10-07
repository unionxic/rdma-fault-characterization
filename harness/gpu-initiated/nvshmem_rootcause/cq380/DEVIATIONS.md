# Deviations and clarifications after pre-registration

`predictions.csv` and sections 2, 3, 7 and 8 of `EXPERIMENT.md` are fixed by tag `prereg/cq380-v1`
(2026-10-07 09:27:09 +0900). Nothing below changes a prediction or an acceptance rule.

## 2026-10-07, smoke runs before the main run (09:27 to 09:49)

1. **How the CQ is read when a kernel is stuck.** The pre-registration says PE 0 scans the CQs
   itself (the `CQSCAN` lines). Smoke runs showed that this cannot work in the stock CPU-proxy
   kill case:
   - The CQ buffers are in GPU memory even with the `cpu_host_memory` handler
     (`cudaPointerGetAttributes` type 2), so the CPU cannot read them directly.
   - A scan kernel on its own non-blocking stream did not finish within 5 s while
     `put_signal_quiet` was stuck, also with all buffers allocated before the first iteration.
   - So `trace_trial.sh` now reads the buffers from outside: the program prints each CQ's device
     address at start, waits 40 s after a failed scan (`CQSCAN hold`), and cuda-gdb prints the whole
     buffer with `x/<ncqes*64>xb (@global unsigned char *)<addr>`. `cqdump.py` decodes it the same way
     the program does.
   - cuda-gdb's `dump binary memory` was tried first and returned zeros: it read the host side of
     the address. `x/` returned the real CQEs (checked byte by byte against a known success CQE and
     an unwritten one), so only `x/` is used.
   - When no kernel is stuck (the other cells), the program's own scan kernel is used, as
     pre-registered. The output reports which path was used (`path=kernel` or `path=cuda-gdb`).
2. **The queues are effectively single-slot.** In every smoke read, each CQ had exactly one written
   CQE out of 1024 (slot 0), in both paths: NVSHMEM 3.8.0 writes its CQEs into one slot here.
   "Valid success CQEs in the RC queue" (C1's guard) therefore means that slot holds a success CQE.
3. **This changes how the exclusion rule in section 8 applies.** Section 8 counts a trial whose scan
   failed (`CQSCAN failed`) as not observable. With item 1, every stock CPU-proxy kill trial prints
   `CQSCAN failed` and is then read by cuda-gdb. `score.py` scores those trials from the cuda-gdb
   read. Read strictly, section 8 makes C1 not observable in every trial; the score reports both
   readings. The change was made during the smoke runs, before the main run started at 09:49:22:
   the last program build is 09:36:37, the first cuda-gdb smoke read 09:38:10, the final
   `trace_trial.sh` and `cqdump.py` 09:46:26 (file times). No main-run data existed then.
4. **The program changed after the tag.** Section 5 lists `cq_repro.cu` md5 `f7de87cf`. The main run
   used md5 `e65c967e` (both nodes, checked 2026-10-07 09:53): the scan buffers are allocated once
   before the first iteration, the device state is copied at start to print each CQ's address and
   memory type (`CQSCAN prep`), the result line names the read path, and `CQSCAN_HOLD_S` adds the
   hold. The scan logic (byte 63, 0xf unwritten, 0xd and 0xe errors, bytes 55 and 54) is unchanged.
   `../official380/run.sh` passes `CQSCAN_HOLD_S` through (one line).
5. **Read time in the CPU-proxy kill cell.** Section 6 says the CQ is read at the 30 s wait limit. With
   item 1 it is read about 35 s to 40 s after the wait started (30 s limit, 5 s scan attempt, cuda-gdb
   attach). The process is still stuck in the same wait.
6. **Queue numbers differ between the two paths.** Each run has 3 CQ slots (1 DCI, 2 RC, one per PE).
   The RC slot for PE 0 itself has no buffer and is skipped. The cuda-gdb read keeps the slot number
   (`cq=2`); the kernel scan numbers the queues it printed (`cq=1`). Both are the RC queue to PE 1;
   `score.py` uses the type, not the number.
