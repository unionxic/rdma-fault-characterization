# GPU-initiated RDMA: fault characterization design (stage 3 of the project)

The harness (`../`) characterizes RDMA faults on CPU verbs by their CQE fingerprint
(`ibv_wc_status` + `vendor_err`), and the NCCL patch (`../nccl-integration/`) recovers one
class of them inside NCCL's CPU proxy path. The research target is fault tolerance of
**GPU-initiated** RDMA (NVSHMEM IBGDA, DeepEP, NCCL GIN), where a GPU thread posts the
WQEs and polls the CQ. A source survey (2026-09-23) found that none of these stacks decodes
the fingerprint in production builds and none resets a QP:

| stack | who sees the error CQE | what happens today (from source) |
|---|---|---|
| NCCL GIN proxy (2.28.7+) | CPU progress thread (`ibv_poll_cq`) | WARN with status/vendor_err, then the progress thread exits; the GPU spins on queue credits with no bound |
| NCCL GIN GDAKI | GPU thread | only REQ_ERR -> -EIO; the timeout wait treats it as "not done" until timeout; the blocking wait discards it (counts as success); the host polls QP state at most every 10 s, only inside `ncclCommGetAsyncError` |
| NVSHMEM IBGDA | GPU thread, collapsed (1-slot) CQ in GPU memory | only REQ_ERR checked, then `assert` (a no-op with NDEBUG) |
| DeepEP legacy | GPU thread | the opcode is never read; an error is taken as success, or a ~100 s trap. Needs SM90: cannot run here |

This stage measures that behaviour on real hardware, then prototypes device-side
classification.

## Questions

- **Q1 (CPU, no GPU).** After the first error CQE, which further CQEs does the NIC write
  (flush CQEs for signaled and unsignaled WQEs, in what order)? Hence: what does a single-slot
  collapsed CQ hold at the end, the root-cause CQE or a flush CQE?
- **Q2 (GPU).** For each stack we can run (GIN proxy, GIN GDAKI, NVSHMEM IBGDA) and each fault:
  which layer notices, whether the fingerprint is visible anywhere, whether the device wait
  times out / hangs / returns success, whether the delivered data is correct, how long until
  the host learns about it, and whether teardown returns.
- **Q3 (GPU, NVSHMEM).** Read the collapsed CQ slot from device code after a fault: opcode,
  syndrome, vendor_err_synd, wqe_counter. This measures Q1's prediction directly.
- **Q4 (GPU, prototype).** Can device code map (syndrome, vendor_err) to our fault classes and
  hand the result to a host thread through a pinned mailbox within bounded time?

## Fault catalog for GPU-initiated stacks

| id | fault | how it is injected | expected CQE on the initiator |
|---|---|---|---|
| F1 | `local_err` | host moves the initiator's QP to ERR while the kernel is posting (env-gated test hook in the library) | WR_FLUSH 5 / 0xf5 |
| F2 | `rem_access` | the kernel writes past the end of the remote window / heap | REM_ACCESS 10 / 0x88 |
| F3 | `peer_err` | the target process moves its own QP to ERR (test hook), process stays alive | RETRY_EXC 12 / 0x81 |
| F4 | `proc_kill` | SIGKILL of the target process mid-run | RETRY_EXC 12 / 0x81 |

Not included: RNR (these stacks post no SENDs, and rnr_retry is 7), and link_down (the link
carries the user's NVMe-oF storage).

IB timeout: runs use 14 (retry-exhausted detection near the ~3.7 s firmware floor) to keep
trials short; one reference run per stack uses the library default (20, about 34 s computed).

## Per-trial record (common CSV columns)

`stack,backend,fault,wait_mode,trial,iters_ok_before,init_outcome,target_outcome,data_check,
silent_success,host_error,host_error_ms,fp_where,status,vendor_err,teardown,notes`

- `wait_mode`: `timeout` (bounded device wait) or `blocking` (the library's unbounded wait,
  bounded only by a host watchdog that kills the process).
- `init_outcome` / `target_outcome`: `ok`, `timeout`, `error`, `trap`, `hang_killed`, `killed`.
- `data_check`: receiver compares every byte with the expected per-iteration pattern:
  `ok`, `mismatch`, `missing`, `n/a`.
- `silent_success`: 1 if the initiator's wait reported success for an operation whose data
  did not arrive intact.
- `fp_where`: where the fingerprint was visible: `log`, `cqe` (read by our device code),
  `api` (returned by an API), `none`.
- `teardown`: `clean`, `hang` (bounded by a watchdog), `n/a`.

## Rules for every cluster run

- Every run goes through `common/cluster_run.sh`, which serializes cluster use and waits for
  an idle link (the link is shared with the user's NVMe-oF storage and gdsio benchmarks).
- No link toggles, no module reloads, no driver or network changes, no system-wide installs.
  Libraries are built from source under the session scratch directory with CUDA 12.8.
- Only processes we started are killed, by PID or `pkill -x <our binary>`.
- Every wait is bounded; remote processes are cleaned up after each trial.
- rain's BAR1 is 256 MiB: registered / symmetric memory stays at or below 64 MiB.

## Layout

- `common/`: `cluster_run.sh`.
- `cqe_seq/`: Q1 (CPU verbs, reuses `../common/probe.c` and `../server/probe_server`).
- `gin/`: Q2 for NCCL GIN (proxy and GDAKI backends): patch, driver, scripts, results.
- `nvshmem/`: Q2 and Q3 for NVSHMEM IBGDA: patch, driver, scripts, results.
- `RESULTS.md`: the combined result table and conclusions.
