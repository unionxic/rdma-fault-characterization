# Official NVSHMEM v3.8.0-0 reproduction

The doorbell-record bug reproduced on the unmodified release, with a test program that uses only
the public API. This is the evidence and the logs for the upstream issue
(`../UPSTREAM_ISSUE_DRAFT.md`).

| File | What |
|---|---|
| `kill_repro.cu` | PE 0 loops put + signal + `nvshmem_quiet()` to PE 1, one kernel per iteration. The host bounds each iteration (`hang_s`). PE 1 waits for each signal. |
| `fix.diff` | The two-line fix against v3.8.0-0. |
| `build.sh` | Builds v3.8.0-0 from the GitHub tag archive, then a second ibgda plugin with only `fix.diff`. Builds the reproducer and deploys `~/gi-bundle/nvshmem_off380` to both nodes. |
| `run.sh` | One trial: stock or fix, NIC handler, kill or not. Prints one CSV row with rain's port-counter deltas. |
| `all.sh` | The matrix (11 trials), run inside `cluster_run.sh`. |
| `redact.py` | Copies logs for the issue with hostnames and IPs replaced. |

```
W=<work dir> bash build.sh
../../common/cluster_run.sh -t off380 -- timeout -s KILL 1500 bash all.sh ../results/20261001_official380
```

## Result (2026-10-01 20:35-20:39, `../results/20261001_official380`)

PE 1 was SIGKILLed after PE 0's iteration 3; iteration 5 is the first one after the kill.

| Library | NIC handler | Iteration 5 | Trials |
|---|---|---|---|
| stock | `cpu_host_memory` | `nvshmem_quiet()` not returned after 30 s | 3/3 |
| stock | `gpu` | returned after 3537-3755 ms, later ones in 1.1 ms | 3/3 |
| fix | `cpu_host_memory` | returned after 3744-3792 ms, later ones in 1.1 ms | 3/3 |

- Without the kill (stock and fix, 1 each), all 40 iterations returned in 1.0-2.2 ms.
- rain's port `hw_counters` did not move in any trial (`req_cqe_error`, `local_ack_timeout_err`
  and the others: +0). NVSHMEM's DEVX QPs are not counted there, as in NVIDIA/nvshmem#64.
- The kill time is in `trials.csv`. The runner's marker line in the pe0 log was overwritten,
  because PE 0 writes the log without O_APPEND.

The stock and fix bundles differ only in `nvshmem_transport_ibgda.so.7.0.0`. Rebuilding the stock
plugin after reverting `fix.diff` gives a bit-identical file (md5 `4aa4dda2`). The fix plugin is
`e5935238`.
