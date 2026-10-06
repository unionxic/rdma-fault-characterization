# official380: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`../../propagation/review_20261006/nvshmem.md`)
- GPU 핸들러와 수정본의 "returned"는 API 수준에서 조용한 성공이다. 상대가 죽었는데도 40회 반복이 모두 돌아왔다. 이 결과를 근거로 한 이슈 초안의 "Expected: returns after about 3.7 s"도 같다. 수정은 멈춤을 조용한 성공으로 바꿀 뿐이다.
- 3.8.0에서는 F4만 돌렸고, CQ 슬롯 읽기와 finalize가 없다. 3.8.0의 오류 코드와 종료 동작은 재지 않았다.

The doorbell-record bug reproduced on the unmodified release, with a test program that uses only
the public API. This is the evidence and the logs for the upstream issue
(`../UPSTREAM_ISSUE_DRAFT.md`).

| File | What |
|---|---|
| `kill_repro.cu` | PE 0 loops put + signal + `nvshmem_quiet()` to PE 1, one kernel per iteration. The host bounds each iteration (`hang_s`). PE 1 waits for each signal. With `FINALIZE=1` each PE calls `nvshmem_finalize()` when its run ends, under a 30 s watchdog (below). |
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

## Teardown timing (`FINALIZE=1`, added 2026-10-06 for the propagation campaign)

The default run never calls `nvshmem_finalize()`, and the result above comes from that mode.
With `FINALIZE=1`, `run.sh` passes the variable to both PEs. Each PE then calls
`nvshmem_finalize()` wherever its run ends: after all iterations, at the `hang_s` bound, or after
a failed kernel. A watchdog thread bounds the call to 30 s. The PE prints one line:
- `PE <n>: nvshmem_finalize returned after X ms`, and keeps the exit code of the end path
  (0, 3 or 4);
- or `PE <n>: nvshmem_finalize did not return after 30 s`, and exits 5.

These lines start with `PE <n>:`, so `run.sh`'s `pe0_last` (the last `^PE 0 ` line) is the same
iteration line as before. The finalize result shows as `pe0_rc` = 5 and in the logs. At the
`hang_s` bound the stuck kernel is still running when finalize is called.

Checked locally with `nvshmem_finalize` replaced by a sleep:
- the default exits without the call;
- a 120 ms sleep gives "returned after 120.1 ms" and keeps the exit code;
- a 40 s sleep gives "did not return after 30 s" and exit 5.

Not yet run on the cluster.
