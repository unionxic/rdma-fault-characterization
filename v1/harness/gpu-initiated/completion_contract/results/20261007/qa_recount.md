# Independent recount: completion_contract main run, 2026-10-07

Recounted from the raw logs by [qa/recount.py](../../qa/recount.py) (`python3 qa/recount.py` from the
experiment folder; prints to stdout, writes nothing). It does not read `score.py`, `SCORE.md` or
`trials_scored.csv`, and this note has not been compared with them.

Rules used: `predictions.csv` (sha256 matches `PREREG.txt`) and `EXPERIMENT.md` sections 3.2, 7 and 8,
which have no diff against tag `prereg/completion-contract-v1`, read with `DEVIATIONS.md` items 1, 3, 4
and 5.

## Method

- **Trial set.** Progress lines in `run_all.out`, trial numbers in each `trials.csv` and `gin.csv`, and
  the per-trial files.
- **NVSHMEM (P1–P3).** Each `*.pe0.log` gives the per-iteration lines (`returned after X ms` or
  `has not returned after S s`).
  - For a kill trial, the script takes the first iteration after iteration 3 that took more than 100 ms
    or did not return (DEVIATIONS 1), and checks that every earlier iteration took less than 100 ms.
  - The handler comes from `NIC handler will be ...` in both PE logs.
  - The plugin build comes from the source path compiled into the IBGDA plugin's messages
    (`nv345/ahinit/...` or `nv345/nvshmem-3.4.5-0/...`) and from its line numbers, which are one higher
    after the added memset (for example `NIC handler will be CPU ...` is at line 4014 in ahinit and at
    line 4013 in stock in the smoke run). The library directory itself (`LD_LIBRARY_PATH`) is not printed.
- **NCCL (P4–P7).** Both ranks' `.kv` and `.log` files give:
  - completed iterations, the device wait result and its time, and the target data check;
  - the host error text and its time;
  - the fault time: the local QP error hook line on rank 0, the peer QP error hook line on rank 1
    converted with the measured clock offset, and `fault_mono_ms` for the remote access error;
  - the polling fallback phrase, `Init COMPLETE` and `devComm created`.

  Times are relative to rank 0's start, as in `run_trial.sh`.
- **Comparison.** Every `trials.csv` and `gin.csv` field listed under "Records against logs" was
  compared with the value recomputed from the logs.

## Trial set `[측정]`

- `run_all.out` has 55 progress lines: P1 10, P2 5, P3 5, P4 10, P5 5, P6 15 (local QP error 5, remote
  access error 5, peer QP error 5), P7 5. The wrapper exited with rc 0 and ran 14:27:22–14:55:41.
- In every cell the trial numbers run 1 to n with no duplicate or gap, in `run_all.out` and in
  `trials.csv` and `gin.csv`. Every trial has both PE or rank logs, and every NCCL trial has both `.kv`
  files.
- The files belong to the right trials. Every kill time in `trials.csv`, and the first and last time
  stamps of every NCCL rank 0 log, fall between that trial's progress line and the one before it.
- Smoke runs exist in `../20261007_smoke/` and are not scored: `gin` 6 rows, `nvs` 3, `nvs2` 3,
  `nvs3` 3.
- The settings in the 20 NVSHMEM main-run trials match DEVIATIONS 2–4:
  - every `PE 0 ready` line shows `hang_s=90`, and every trial logs RC map `cta`;
  - P1 and P3 run the ahinit IBGDA plugin on both PEs with handler "CPU with host memory backend";
  - P2 runs the stock plugin on both PEs with handler "GPU".
- All 35 NCCL trials ran with `ib_timeout=14` (the `.out` files).

## Verdicts

| Cell (ID) | Prediction | Frozen rule | n | Hits | Misses | Counted apart | Verdict |
|---|---|---|--:|--:|--:|--:|---|
| NVSHMEM 3.4.5 CPU proxy with the DCT init fix, peer killed (P1), reading (a), as written | First iteration after the kill returns after the retries run out, 3–5 s | 9 or more of 10 in the window, and no trial that does not return within 30 s | 10 | 0 | 10 | 0 | **fails**: 10/10 outside the window, and 10/10 took longer than 30 s |
| Same cell (P1), reading (b), ack timeout 20 | Same, with a 50–70 s window | 9 or more of 10 in the window, and none beyond the 90 s bound | 10 | 10 | 0 | 0 | **holds** |
| NVSHMEM 3.4.5 stock, GPU handler, peer killed (P2), reading (a) | Same as P1, 3–5 s | 5/5 | 5 | 0 | 5 | 0 | **fails** (all 5 also took longer than 30 s) |
| Same cell (P2), reading (b) | 50–70 s, 90 s bound | 5/5 | 5 | 5 | 0 | 0 | **holds** |
| NVSHMEM 3.4.5 CPU proxy with the fix, no kill (P3) | All iterations return | 5/5 | 5 | 5 | 0 | 0 | **holds** |
| NCCL GDAKI, BlueFlame handler 6, no fault (P4) | The first wait does not complete (it times out at the device bound), and the target has no data | 9 or more of 10, and no normal completion | 10 | 10 | 0 | 0 | **holds** |
| NCCL GDAKI, default handler, no fault (P5) | All iterations complete normally | 5/5 | 5 | 5 | 0 | 0 | **holds** |
| NCCL GDAKI, CPU proxy handler 1, local QP error (P6, F1) | A host error from `ncclCommGetAsyncError` in event mode | 5/5 per fault | 5 | 5 | 0 | 0 | **holds** |
| Same, remote access error (P6, F2) | Same | 5/5 | 5 | 5 | 0 | 0 | **holds** |
| Same, peer QP error (P6, F3) | Same | 5/5 | 5 | 5 | 0 | 0 | **holds** |
| NCCL GDAKI, handler 1, no fault (P7) | Complete normally with no host error | 5/5 | 5 | 5 | 0 | 0 | **holds** |

Counted apart (section 8 and DEVIATIONS 1). Each class is zero:

- kill trials with no iteration over 100 ms after iteration 3: 0 of 15;
- P4 trials where initialization refused handler 6: 0 of 10 (both ranks print `Init COMPLETE` and
  `devComm created`);
- trials whose logs contain the phrase `falling back to polling-based errors` (counted as "unobservable"):
  0 of 15 in P6 and 0 of 5 in P7;
- fault-not-applied trials in P6: 0 of 15.

A trial counts as a hit when:

- **P1, P2:** the duration of the first slow iteration lies in the window, and every earlier iteration
  took less than 100 ms.
- **P4:** rank 0 has `iters_ok=0` and `device wait returned ncclTimeout` at iteration 0, and rank 1 has
  `data_check=missing`. A normal completion would be rank 0 outcome `ok` or any `it N ok` line, and
  there is none.
- **P5, P7:** rank 0 has outcome `ok`, both ranks have `iters_ok=120`, and rank 1 has `data_check=ok`.
  For P7, neither rank also reports a host error.
- **P6:** either rank reports a host error after the fault time.

## Values `[측정]`

| Quantity | Range | n |
|---|---|--:|
| P1: duration of the first iteration after the kill, one value per trial (always iteration 5) | 56970.1–58474.4 ms; trials 2–10 in 56970.1–57029.2 ms, trial 1 at 58474.4 ms | 10 trials |
| P2: same | 56967.7–57013.4 ms | 5 trials |
| All other PE 0 iterations, pooled over the trials of one cell | P1 1.0–1.8 ms, P2 1.1–1.8 ms, P3 1.0–1.9 ms | 390, 195, 200 iterations |
| P1, P2: last signal PE 1 received before the kill | iteration 4 in every trial | 15 trials |
| P4: device wait until `ncclTimeout`, one value per trial | rank 0 4781.1–4807.4 ms, rank 1 4118.5–4145.8 ms. The nominal bound is 5000 ms on both ranks (rank 0: 9075000000 cycles at 1815000 kHz; rank 1: 7800000000 at 1560000 kHz) | 10 trials |
| P6 local QP error: fault time; host error time; host error after the fault (times from rank 0 start) | 1350.6–1401.4 ms; 10754.7–10806.1 ms; 9402.8–9404.7 ms | 5 trials |
| P6 remote access error: same | 738.4–755.7 ms; 10739.3–10756.2 ms; 10000.5–10000.9 ms | 5 trials |
| P6 peer QP error: same | 1344.0–1409.8 ms; 10747.2–10811.8 ms; 9402.0–9403.3 ms | 5 trials |
| P6: iterations completed before rank 0's device wait timed out | local QP error 36 (4 trials) or 37 (1); remote access error 0; peer QP error 36 | 15 trials |
| P6: rank 0 device wait until `ncclTimeout` | 4743.5–4790.8 ms | 15 trials |

## Records against logs

**Compared fields.**

- `trials.csv`: variant, handler setting, kill flag, handler from the log, a kill time present exactly
  when kill=1, the last `PE 0 iter` line, and pe0 rc against "all 40 iterations returned".
- `gin.csv`: `iters_ok_before`, `init_outcome`, `data_check`, `host_error`, `host_error_ms`,
  `fault_ms`, `surface_ms`, `surface_by`, `qps_moved`, and r0rc against rank 0's `DONE ... exit=`.

**No field differs** from the value recomputed from the logs (times within 0.15 ms) `[측정]`.

Other findings:

1. **The kill marker is missing.** The runner's `=== runner: SIGKILL PE 1 at ... ===` line is absent
   from all 15 kill-trial PE 0 logs `[측정]`. `run.sh` appends it with `>>`, while PE 0 is still writing
   to the same file through a descriptor opened with `>` (not append), so PE 0's later output
   overwrites it `[추론]`. The kill time now exists only in `trials.csv`. The PE 1 logs still bound the
   kill: in all 15 trials their last line is the signal for iteration 4.
2. **The NIC counters do not move.** The counter deltas (ack timeout, CQE error, flush, remote access on
   rain mlx5_1) are `0;0;0;0` in all 20 NVSHMEM trials, including the 15 with a 57 s stall `[측정]`. The
   3.8.0 run is all zero too ([`../../../nvshmem_rootcause/results/20261001_official380/trials.csv`](../../../nvshmem_rootcause/results/20261001_official380/trials.csv),
   11 rows). So these counters give no evidence about retry exhaustion either way. Why they stay at
   zero is `[미확인]`.
3. **The reproducer prints durations only, not completion status.**
   - The claim that the 57 s return is retry exhaustion rests on the duration matching ack timeout 20
     `[추론]`.
   - Whether `nvshmem_quiet` saw an error completion is not in these logs `[미확인]`.
   - After iteration 5, every later iteration returned in about 1.1 ms with PE 1 dead. In all 15 kill
     trials PE 0 printed "all 40 iterations returned" and exited with rc 0 `[측정]`.
4. **The P4 wait ended before its nominal bound.** It ended about 0.2 s before the nominal 5.0 s on
   rank 0 and about 0.86 s before it on rank 1 `[측정]`. The bound counts GPU cycles at the printed
   clock rate, so the GPUs probably ran faster than that rate `[추론]`. The wait still ended with
   `ncclTimeout`, not by completing, in 10/10.
5. **No NCCL log names the handler**, as section 8 anticipates. P5 (default handler) and P7 (handler 1)
   were compared trial by trial, both ranks, five pairs. Their logs differ only in ports, QP numbers,
   pointers and keys, CPU cores and timings. The handler of P4, P6 and P7 is
   therefore known only from `run_cells.sh` `[미확인]` from the logs. P4 behaves differently from P5,
   so the handler 6 setting did reach the library `[추론]`.
6. **The polling fallback phrase is absent** from all 70 NCCL rank logs `[측정]`, although the string is
   in the deployed `libnccl.so.2.32.3` `[측정]`. The NCCL source at the bundle's printed git version
   (12df1a1) logs the phrase with `INFO(NCCL_NET, ...)` in `gin_host_gdaki.cc`. This run set
   `NCCL_DEBUG=INFO` with NET in `NCCL_DEBUG_SUBSYS`, so the phrase's absence means the completion
   channel was created and the host error came in event mode `[추론]`.
7. **P6 host errors came only from rank 0.**
   - Rank 0 reported the host error in 15/15 trials. Rank 1 reported none within its 15 s poll, even in
     the peer QP error trials, where rank 1's own QPs were moved to error `[측정]`.
   - The text is ncclRemoteError's ("remote process exited or there was a network error") for all three
     faults. `gin.csv` keeps only its first word, "remote".
   - "GIN Error detected" appears in all 15 P6 rank 0 logs and in no other NCCL log.
8. **`trials.csv` format.**
   - The files have no header row. The 3.8.0 run's file has one.
   - The `pe0_last` column holds the last `PE 0 iter` line, not the final "all 40 iterations returned"
     line, because `run.sh` greps `^PE 0 ` and the final line starts `PE 0:`.
9. **`DEVIATIONS.md` item 5 (trial count 55) is not committed yet.** It exists only in the working tree
   (`git status` shows the file modified) `[측정]`. The main run matches it.
10. **The raw logs contain the management network address**, in the NVSHMEM bootstrap lines and the NCCL
    OOB lines. They need the same redaction as earlier Release uploads before they are published. This
    note does not repeat the address.
