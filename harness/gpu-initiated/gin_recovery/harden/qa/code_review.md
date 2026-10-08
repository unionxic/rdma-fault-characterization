# Code review: gin-harden measurement code

Independent review, 2026-10-09. Read-only: this file is the only change. Nothing was built, deployed or run on the cluster,
and `score.py` was not re-run. Values below come from `results/20261009/trials_scored.csv` and were recounted from the
per-trial kv, log, meta, kill and mute files with read-only Python.

**Scope.**
- The driver [../gin_ts2.cu](../../gin_ts2.cu) as changed on this branch (commit `b869cfdd`).
- [run_trial_hd.sh](../run_trial_hd.sh), [cells.sh](../cells.sh), [hold.sh](../hold.sh), [chain.sh](../chain.sh),
  [deploy_hd.sh](../deploy_hd.sh), [build_hd.sh](../build_hd.sh), [rows_hd.py](../rows_hd.py), [score.py](../score.py).
- The shared code they call: `../scripts/ts2/rows.py`, `../s2_close/rows_extra.py`, `../s2_close/score.py` (grammar),
  `../pair_check/rows_pc.py`, `../oneway/rows_ow.py`.
- The library only where the harness depends on it: `ncclGinGetRecoveryStats` (`src/nccl.h.in` and
  `gin_host_gdaki.cc` 5727 of the build tree `agent_ts2hd/nccl-src`) and the helper port binding (`gin_host_gdaki.cc`
  5096–5121). The library layer itself was reviewed by someone else (EXPERIMENT.md 9 (g)).

Tags: `[측정]` counted from raw files, `[소스]` read in code, `[추론]` reasoning, `[미확인]` not checked. Line numbers are
in the file named in the "Where" column.

## Verdict

**Usable, no blocker.** In this run nothing in the measurement code makes a failed operation look successful, or the
reverse. The 52 verdicts in `SCORE.md` follow from the frozen rules applied to these data. Two verdicts need a narrower
interpretation than the document now gives:
- The GPU-fill cell (C1) did not have a full GPU at the fault (H1 below).
- The shrink cell (A2) measured a shrink called while the devComm holding the GIN error was still registered (M2).

The runner kept to the safety rules in every trial. It has one observed defect: four rendezvous bind failures (M1). They
cost refills but cannot have changed a verdict.

## Baseline checks `[측정]`

- **Tag.** HEAD = `prereg/gin-harden-v1` = `692ff591`. Every in-scope file and every shared extractor is byte-identical to
  its tagged blob, read with `git show`. The only exceptions are the `SUNNY_SSH` default lines (`run_trial_hd.sh` 33,
  `hold.sh` 15, `deploy_hd.sh` 15), which the repository's address filter rewrites on checkout. The shared extractors did not
  change between the base `d834f86c` and the tag. The sha256 of `predictions.csv` is `0e9e3192…`, the same as `PREREG.txt`.
  Nothing changed after the tag that affects scoring.
- **Driver.** The source md5 is `f34e65f0`, as in section 5. The deployed binaries `c0b73e09` and `472602a2` equal
  `agent_ts2hd/out/drv*/gin_ts2`, which were built after the source's last change.
- **Run.** 247 trials: 243 `scored`, 4 `bind`, no other status. Every meta file has `left=0` and `left_rules=0` (247/247).
  There is no `STOP_*` file. Every chain cleanup reported `deleted=0 left=0` (9 holds). Holds lasted 33–625 s (snap before
  to snap after), all under the 880 s bound, and every hold has `rc=0`.
- **Exit codes.**
  - `r0rc`: 0, 3, 4, 1 (the 4 bind trials) and 137 (the 20 rank-0 kill trials).
  - `r1rc`: 0, 4, 7 (3 bind trials) and 255 (the 31 rank-1 kill trials).
  - No code 2, 6 or 139 appears, and no log or kv has "illegal" or "unspecified launch failure". No trial failed in NCCL or
    CUDA initialization.

## Findings, ranked

| # | Severity | Where | Finding | Effect on the measured results |
|---|---|---|---|---|
| H1 | high (interpretation) | `gin_ts2.cu` 1073–1091, 1001–1022; `predictions.csv` 18 (C1); `rows_hd.py` 252–255, 264 | The GPU-fill cell never had a full GPU at the fault. Between the GIN launch and the fill launch the driver loads the fill kernel (occupancy query), calls `cudaMalloc` and creates a stream. In that order the fill kernel does not start beside the GIN kernel, and the helper's copies wait for the GIN kernel to end. No column checks that the fill blocks ran | C1's 0/10 stands as scored. It measures "the application makes CUDA calls while a GIN kernel runs", not "the GPU is full". H3's GPU-full clause is not tested by this run. Five places in the document describe the cell wrongly (list below) |
| M1 | medium (observed) | `run_trial_hd.sh` 41; `gin_ts2.cu` 818–832, 838–845 | The rendezvous port 46000–48999 lies inside rain's ephemeral range 32768–60999. 4 of 247 trials failed `bind` | No verdict changed. Four refills ran 0.5–2.3 h after their holds. Rank 1 might have connected to another process's listener `[미확인]` |
| M2 | medium (interpretation) | `gin_ts2.cu` 1117–1131 | The driver calls shrink while the devComm holding the GIN error is still registered. A later control showed that destroying the devComm first gets past stock NCCL's check | A2's 0/10 stands as scored. "Stock NCCL cannot shrink after a GIN error" (sections 3, 9 (g), 19) is too broad |
| M3 | medium (latent) | `score.py` 139–178 before 179–231 | The fault, kill and order exclusions are checked before the configuration checks, and there is no status for an initialization failure. A library failure before the hook, kill or order point is excluded and refilled; it is neither scored nor a reason to stop the block | None: 0 such trials |
| L1 | low | `predictions.csv` 5 (A4) | `or not nonempty(ho_shrink_rc)` is also true when rank 0's kv lacks the key for any other reason | None: 5/5 passed on the other branch |
| L2 | low | `predictions.csv` 50 (P7) | The rule checks only the "transparent recovery ON" line, but production logs still carry a WARN line about a clamped default setting on every rank | Verdict correct by its rule. The prediction's wording claims more than the rule checks |
| L3 | low | `rows_hd.py` 280; `run_trial_hd.sh` 140–142 | `mute_applied` does not check whether the two `iptables -I` calls succeeded | None: 5/5 trials had `mute_rules_on=2` |
| L4 | low | `hold.sh` 100–107; EXPERIMENT.md 8 | Some stop rules exist only in the text. The exit-code check for 139 cannot see rank 1 | None: the triggering conditions never occurred |
| L5 | low | `cells.sh` 93–94; `run_trial_hd.sh` 129–137 | The muted helper ports 51700–51715 are also ephemeral ports. The foreign-socket check sees only sockets that exist when the window starts | None seen |
| L6 | low | `gin_ts2.cu` 869–870 | Device wait bounds are counted in cycles at `cudaDevAttrClockRate`. On sunny they end about 17% early: the "15 s" wait ended 12 351–12 459 ms after the kill | None: B10's threshold is 10 000 ms |
| L7 | low (latent) | `gin_ts2.cu` 1140–1145 | If shrink succeeds, the driver creates a stream and calls `cudaMalloc` while the old kernel may still run (the pattern in H1) | None: this path never ran (0 of 15 shrinks succeeded) |
| L8 | low | `gin_ts2.cu` 1415, 208–225 | In shrink mode the stats are read after `ncclCommShrink(NCCL_SHRINK_ABORT)`. They are never read on early exits | None in this run |

## Details

### H1. The GPU-fill cell's condition did not occur (high, interpretation)

**What the driver does** `[소스]`.
- Lines 1001–1022 load every kernel before the launches, because a launch that has to load a kernel or grow the local
  memory can wait for kernels already running (the comment there). The fill kernel (`hogKernel`, 678–683) is not on that
  list.
- Lines 1073–1091 run after the GIN kernels are launched (1035–1070):
  - `cudaOccupancyMaxActiveBlocksPerMultiprocessor(hogKernel)` (1080) is the first use of the fill kernel, so it is
    loaded here;
  - then `cudaMalloc(&dSink)` (1082) and `cudaStreamCreateWithFlags(&st3)` (1083);
  - then the wait for the first iteration (1085) and the launch (1087).

**What this run shows** `[측정]`, `hd_hog_f1_b@hd`, n=10:
- kv `hog_launch_after_launch_ms` is 0.2–0.4 ms on both ranks.
- Both ranks logged one copy-timeout line (`n_copyto` 1). Rank 0 declined with "the watchdog surfaced a fault earlier";
  rank 1 declined with "the peer declined". No initiator recovery.
- Rank 1 runs more GPU work after the GIN kernel: the host check and the final signal read (1353, 1379–1380). Its abort
  started 3 299.2–3 300.3 ms after its GIN kernel ended (n=10; kv `abort_start_mono_ms − launch_mono_ms − kernel_ms`). In
  `f1_b@hd` the same interval is 353.9–379.3 ms (n=5).
- `[추론]` 3 300 ms is the fill length (3 000 ms) plus the end wait (300 ms). So on rank 1 the fill kernel ran its 3 000 ms
  from about the end of the GIN kernel (2 081–2 096 ms after launch), not from 0.2 ms. Had it started at 0.2 ms, the extra
  wait would have been about 1 200 ms.
- Rank 0 runs no kernel after the GIN kernel. Its kv cannot show when its fill kernel started: `hog_running_at_end=1` at
  2 364 ms would hold either way.

**What the follow-up measured directly.** gin-handoff ran the same call order; I recounted from its raw kv and logs
`[측정]`. The files are in the `exp/gin-handoff` worktree, `handoff/results/20261009/hf/`. That study is scored but has
not finished QA. Its library `hf` is this `hd` layer plus a shrink hand-off layer.

| Cell (gin-handoff) | Calls between the two launches | n | Fill blocks started at the probe (rank 0, rank 1) | New-stream 4 B copies done within 200 ms | Rank 0 |
|---|---|--:|---|---|---|
| `hf_hog_f1_b` | as in gin-harden | 5 | 0, 0 | 0/8 on both ranks | copy timeout, no recovery; both outcomes `device_error` |
| `hf_hogpre_f1_b` | none (calls made before the GIN launch) | 5 (n2–n6; n1 was a bind failure) | 191 of 192, 287 of 288 | 8/8 on both ranks | one initiator recovery, no copy timeout; both outcomes `ok` |
| `hf_hogpreslack_f1_b` | none, grid one block smaller | 5 | 191, 287 | 8/8 | same as above |

So with nothing between the launches, the GPU was full except for one block per rank, and recovery was transparent.

**The rule does not check the premise** `[소스]`.
- C1 checks `hog_blocks_r0 >= hog_sms_r0`. That is true by construction, because blocks = SMs × blocks per SM.
- C1's fault window is measured from the fill kernel's launch call, not from the start of its blocks
  (`fault_after_launch_r0_ms` against `hog_launch_after_launch_ms_r0`).
- If the copies had finished anyway, C1 would have passed while the fill kernel waited in its queue.

**Effect.**
- C1 = 틀림 (0/10) is the correct outcome of the frozen rule.
- What the cell does show: if the application makes these CUDA calls while its GIN kernel runs, the helper's device-state
  copies wait for that kernel. The 2 s copy bound expires and both ranks decline.
- `[추론]` That is a real risk for the design. An allocator that calls `cudaMalloc` during a long communication kernel
  would hit it. But it is not the GPU-full condition that H3 and C1 describe.
- H3's first falsifier ("GPU가 가득 찬 셀의 투명 복구가 9/10 미만") is met by the rule, but the cell condition was not.
  This run supports no conclusion about recovery with a full GPU.

**Document text to correct.** These are facts about the cell, not changes to the frozen rule. Record them in section 13.
- 3.3, C1 row (line 244): "GPU 전체를 쓰는 커널이 도는 중에도" describes a condition that did not occur.
- 7 (347) and 9.3 (566–567): say that the fill kernel is launched after the driver's three calls, and that in this order
  it did not run beside the GIN kernel.
- 11, pilot check 2 (671–672), and 12 (709, "GPU 채우기 훅은 채우기 시작 599 ms 뒤"): the 599 ms is measured from the
  launch call. The fill kernel had not started.
- 19 (751): the cause is now located (the call order), not SM occupancy.

Suggested wording for the result section:

> GPU 채우기 셀(C1)에서 드라이버는 GIN 커널을 띄운 뒤, GPU 채우기 커널을 띄우기 전에 그 커널의 점유율을 묻고(이때 커널이
> 지연 적재됨) `cudaMalloc`과 스트림 생성을 했다(`../gin_ts2.cu` 1080–1083행). 이 순서에서는 GPU 채우기 커널이 GIN 커널
> 옆에서 시작하지 않고, helper의 장치 상태 복사도 GIN 커널이 끝날 때까지 끝나지 않는다(gin-handoff `hf_hog_f1_b` 5/5). 그래서
> C1의 0/10은 GPU가 가득 찬 동안의 복구가 아니라, 응용 커널이 도는 동안 같은 프로세스가 할당과 커널 적재를 한 뒤의 복구를 잰
> 것이다. 세 호출을 GIN 커널 전에 하면 GPU를 거의 다 채운 상태(블록 191/192, 287/288)에서도 복사가 200 ms 안에 끝나고 투명하게
> 복구됐다(gin-handoff `hf_hogpre_f1_b` 5/5).

**Fix for later studies.**
- Make the three calls before the GIN launch (gin-handoff's `GIN_TS_HOG_PREALLOC=1`), or add the fill kernel to the
  preload block.
- Make the number of started blocks a cell-condition column (gin-handoff's `hog_started_probe`).

### M1. Rendezvous port inside the ephemeral range (medium, observed)

**Where** `[소스]`.
- `run_trial_hd.sh` 41: `PORT=$(( 46000 + ($$ + RANDOM) % 3000 ))`.
- Rank 0 binds `INADDR_ANY:PORT` with `SO_REUSEADDR` and exits 1 on failure (`gin_ts2.cu` 818–828).
- Rank 1 retries `connect` every 200 ms, at most 600 times, and its watchdog thread ends it first (838–845, 808–815).

**Cause.** rain's `ip_local_port_range` is `32768 60999` `[측정]` (read on rain, 2026-10-09), so all of 46000–48999 is in it.
`[추론]` A bind fails if any socket on rain holds the port without `SO_REUSEADDR`, or is a listener on it. Possible holders:
- the runner's own ssh and scp connections to sunny (one is opened just before rank 0 starts, line 73);
- NCCL sockets of earlier trials still in TIME_WAIT;
- sockets of other jobs.

This rests on Linux's bind-conflict rules, not checked against this kernel.

**Observed** `[측정]`. Four trials, with ports taken from the hold outputs:

| Trial | Hold | Port | Rank 1 exit |
|---|---|--:|---|
| `pc_dual_f1c0_r1c2_b_n5@hd` | H1 | 48340 | watchdog (`r1rc=7`) |
| `hd_fwslow_f1_b_n4@ow` | H5 | 46209 | watchdog (`r1rc=7`) |
| `hd_shrink_b_n2@hd` | H6 | 46814 | the runner's kill (`r1rc=255`; the kill record names our PID) |
| `hd_copystall_f1_b_n2@hd` | H6 | 46410 | watchdog (`r1rc=7`) |

Rank 0's whole log is `bind: Address already in use`. gin-multirank found the same mechanism (its review, M1).

**Effect.**
- `[추론]` No verdict changed. The failure comes before CUDA and NCCL start, so it cannot depend on the fault or the
  outcome. `score.py` 139 excludes it before any other check, as section 8 requires. Each affected key was filled once (fill
  hold 06:03:30–06:11:48), within the 50% refill limit.
- The refills ran 0.5–2.3 h after their original holds. They also used a new trial number, so the injection time differs
  but stays in the same range (`inj` depends on `k`, `cells.sh` 16–17).
- In three trials rank 1 idled until its watchdog (45 s in `pc_dual_f1c0_r1c2_b`, 60 s in the other two).
- If the socket holding the port had been another process's listener, rank 1 would have connected to it and waited for 128
  bytes. `[소스]` Rank 1 writes nothing before it has read a full id. So it sends nothing to such a listener unless the
  listener first sends at least 128 bytes. Whether rank 1 connected anywhere is `[미확인]`.

**Fix.** Pick the port below 32768 (for example 20000–29999), or have the runner relaunch with a fresh port after a bind
failure and still count the failed attempt as `bind`. Reserving ports is a system change and is not allowed here.

### M2. A2 depends on the driver's call order (medium, interpretation)

**Where** `[소스]`. `gin_ts2.cu` 1117–1131. After the main wait the driver calls
`ncclCommShrink(g_comm, {1}, NCCL_SHRINK_ABORT)` while the devComm, whose GIN contexts hold the error, is still registered.
It never calls `ncclDevCommDestroy` first.

**Observed** `[측정]`.
- `ho_shrink_rc` was `ncclRemoteError` after 0.0 ms in 10/10 `hd` trials and 5/5 `ow2` trials.
- gin-handoff's control `hf_shrinkdc_b` (n=5, recounted from its kv) used the same driver with
  `GIN_TS_SHRINK_DEVCOMM_DESTROY=1` and that study's own layer switched off (`NCCL_GIN_SHRINK_HANDOFF=0`). All 5/5 trials
  show:
  - `ho_devcomm_destroy_rc=no error`;
  - `ho_shrink_rc=no error`;
  - `ho_newcomm_nranks=1`;
  - `ho_check_ok=1`.

**Effect.**
- A2's 0/10 is the correct outcome of the frozen cell, and that cell includes this call order. A1, A3 and A4 are not
  affected.
- The document claims more than this. See section 3 (141–143), 9 (g) (543) and section 19 (750: "순정 NCCL 2.32.3도 GIN
  오류 뒤에는 shrink를 할 수 없다"). Those sentences should add "while the devComm that holds the GIN error is still
  registered".

### M3. An initialization failure would be excluded, not scored (medium, latent)

**Where** `[소스]`. `score.py` `status_of` runs its checks in this order:
1. `bind` (139);
2. hook fired (141–146);
3. trigger (147–149);
4. kill (150–153);
5. order (154–166);
6. mute (167–168);
7. responder rejection (171–172);
8. firmware overrun (175–178);
9. only then the configuration checks (179–231).

No status covers a trial that fails after the bind but before NCCL is usable.

**Failure scenario.**
- In a hook cell, the `hd` library fails `ncclDevCommCreate`, or crashes before the hook timer (which starts at GDAKI
  context creation). There is no hook line, so the trial is `no_fault`: excluded and refilled.
- In a kill cell, rank 1 crashes before the kill. The kill record says `no_rank1_process`, so the trial is `no_kill`.
- In `hd_rround_f1_b`, the library fails before rank 1's reset, so the trial is `cond_order`.

In each case a library failure is refilled away. It does not count against the prediction, and it does not stop the block
as section 8's configuration rule requires. The firmware-overrun exclusion (175–178) is also correlated with the mechanism
under test, but it was pre-registered.

**Effect.** None here. All 247 trials are `scored` or `bind`, and the exit codes show no initialization failure (baseline
above). `SCORE.md` would also list such trials by name.

**Fix.** Check `r0rc` and `r1rc` and the kv keys `nccl_error` and `cuda_error` first, as their own status that stops the
block.

### Low

- **L1. A4's `or` branch can pass on missing data.**
  - `not nonempty(ho_shrink_rc)` is meant for "shrink never returned". It is also true if rank 0 exits before the shrink
    (for example a CUDA error, exit 6) or its kv is not copied back.
  - The `ow2` configuration check needs only rank 0's start lines, which come before the shrink.
  - Observed: all 5 trials passed on the other branch (`post_abort_rx_phantom_r0` 201–204, `post_abort_read=ok`).
  - Fix: `nonempty(ho_shrink_start_mono_ms) and not nonempty(ho_shrink_rc)`.
- **L2. P7 checks one line.**
  - P7 counts only `ts_on` (the start line).
  - At WARN, every production rank log (10 trials) still has one line about a clamped default setting:
    `GIN/TS: rank=<r> NCCL_GIN_TS_PATH_WAIT_MS=30000 exceeds min(round_ms=25000, hold_ms=30000) - handshake_ms=3000 - 1000;
    clamped to 21000 ms` `[측정]`. The runner sets no `PATH_WAIT`. The same line is in `ow` and `hd` logs, so it predates
    this layer.
  - Otherwise `hdp_mute_b` shows no GIN line at WARN. `hdp_kill_b` shows the death, decline, close and wait-release lines,
    which are WARN by design.
  - The rule passes correctly. The prediction's wording ("WARN에서 정보성 복구 줄을 남기지 않는다") should mention this
    line or exclude it.
- **L3. `mute_applied` ignores failed inserts.**
  - Section 8 lists "sudo 실패" as a reason the cut was not applied. The runner checks `sudo -n iptables -S` before the
    window (127), but not the exit status of the two `-I` calls (140–141).
  - `rows_hd.py` 280 sets `mute_applied=1` whenever `mute_on_mono_ms` is written. A failed insert would be scored as a P6
    failure instead of being excluded.
  - Fix: `mute_applied = (mute_rules_on == 2)`.
  - Observed `[측정]`: 5/5 trials had `mute_rules_on=2` and `mute_rules_left=0`. The cut started 2 050.5–2 086.7 ms after
    rank 0's launch and lasted 8 056.0–8 056.7 ms.
- **L4. Stop rules partly in text only.**
  - Not implemented in code:
    - Section 8's "left > 0이 두 시행 연속이면 멈춘다": `hold.sh` and `chain.sh` never read `left`.
    - The 50% refill limit: `score.py` simply takes the first N candidates.
    - Stopping on a configuration failure: the checks run only at scoring time, so nothing stops a block during the run.
  - `STOP_cuda`'s exit-code test (102) sees 139 only for rank 0. Rank 1's code is ssh's, which is 255 for any signal
    death of the remote `timeout` (the 31 kill-cell trials) `[측정]`. A rank 1 segfault would also show as 255.
  - The text search (103–104) still catches the CUDA errors the driver writes (`cuda_error=` in kv).
  - None of these conditions occurred: `left=0` in 247/247 trials, one refill per affected key, no configuration
    failure, and `r1rc=255` appears only in the 31 kill-cell trials.
- **L5. Muted range in the ephemeral range.**
  - The helper ports 51700–51715 can also be drawn for outgoing connections on rain and sunny.
  - The pre-check (129–137) counts sockets in the range that belong to another PID, but only at the start of the window.
    A connection opened during the 8 s window, by another job or by an ssh in either direction, that gets a port in the
    range would be dropped.
  - The library falls back from 51700 to 51701–51715 (`gin_host_gdaki.cc` 5106–5117), which stays inside the muted range,
    so a taken port does not break the cell.
  - Fix: move the helper port range below 32768.
- **L6. Cycle-based bounds run short on sunny.**
  - `timeoutCycles` and `rxWaitCycles` are seconds × `cudaDevAttrClockRate` (869–870).
  - On sunny `[측정]`:
    - `hd_rxdeath_b@ow` released 12 351–12 459 ms after the kill (n=5), against a stated "15 s" bound;
    - in `to20_f3_t` rank 1's "20 s" wait ended with kernel time 17 255.9 ms (`n1`).
  - On rain, `to20_f3_t` rank 0's "8 s" flush ended with kernel time 8 299.5–8 299.8 ms (n=3). That is consistent with the
    stated value, since the kernel time includes the time before the fault.
  - `[추론]` sunny's SM clock runs above the reported rate.
  - No verdict changes: B10 tests ≥ 10 000 ms. The text "15 s 대기 상한" (242, 346) should say "about 12.4 s on sunny".
- **L7. The shrink success path repeats H1's pattern.**
  - The path creates a stream and allocates (1141–1142) while the old kernel may still run. In `ow2` it was still
    running in 5/5 trials.
  - So the 1-rank allreduce check could stall behind the old kernel and miss its 5 s bound for a reason unrelated to
    shrink.
  - The path never ran: shrink failed 15/15.
  - Fix: allocate `s4` and `dbuf` before the launches.
- **L8. When the stats are read.**
  - `recoveryStats` runs once, at 1415, after the main wait and before `teardownExit` (`ncclCommAbort`). That order is
    correct.
  - In shrink mode the read comes after `ncclCommShrink(NCCL_SHRINK_ABORT)`. No prediction reads `rs_*` in shrink cells.
  - Early exits through `CK` or `NK` (208–225) skip the read. In an `hdp` trial that would turn a crash into the
    configuration status `config_build` rather than a failure. No such trial exists.

## Checked and found correct

- **Recovery stats** `[소스, 측정]`.
  - Looked up with `dlsym`, so `ow2` and `stk` print `rs_api=0` (15/15) and `hd` and `hdp` print `rs_api=1`.
  - The struct fields match the `%d` and `%llu` formats (`nccl.h.in` in the build tree).
  - The counters outlive a decline and an escalation: E4 5/5, E5 5/5, E1 10/10.
- **Flush accounting** `[소스]`.
  - `GIN_TS_FLUSH_BLOCKING` (83–88) is used at all four blocking flush sites (301, 361, 498, 612).
  - For `hd` and `ow2` it is the old call and returns the classified error.
  - For `stk` it is a constant success. That build runs only latency cells, which have no fault.
  - `[추론]` In `stk` the constant removes one compare-and-branch per iteration, far below the 0.1 µs scale of P3 and P4. I
    found no harness cause for P4's 1.05 µs.
- **Waits released without their signal** `[소스, 측정]`.
  - `phantomCount` (687–696) counts the successful waits whose signal value, read after the wait, is below base + i + 1.
    It looks only at iterations the kernel reports done. An error exit stops `done` at the failing iteration.
  - Computed for every one-thread receiver, including the fused bidir receiver.
  - The read after the abort (698–715, 180–187) first waits up to `GIN_TS_POST_ABORT_WAIT_S` for both streams.
  - Values: `hd_shrink_b@hd` 0 in 10/10, with the kernel done before the shrink; `@ow2` 201–204 after the abort in 5/5.
  - `[추론]` A signal that lands between the wait and the read hides a phantom, so the count can only be low. With a dead
    sender that cannot happen.
- **Shrink path** `[소스]`.
  - Rank 0 only, and only with `GIN_TS_SHRINK=1`.
  - Bounded by `alarm(30)`. The new communicator is checked with a 1-rank allreduce (exact float compare, 5 s bound) and
    destroyed under `alarm(15)`. The driver waits 3 s for the old kernel.
  - It sets the read-after-abort only when the old kernel is still running.
- **iptables** `[소스, 측정]`.
  - Rules go in INPUT on rain only. They match sunny's management address as source, TCP, and source or destination port
    51700–51715. Each carries the comment `gin-harden-<runner pid>`.
  - Three things remove them:
    - the window subshell (3 tries);
    - the EXIT trap (3 tries);
    - `chain.sh` after every hold, including a hold killed by its bound.
  - The rules are counted after every trial and every hold.
  - The cut is skipped if `sudo -n iptables -S` fails, or if a socket on rain in the range belongs to another PID (states
    LISTEN, ESTAB, SYN-SENT, SYN-RECV, CLOSE-WAIT; local or peer port).
- **Kills** `[소스, 측정]`.
  - Rank 0: the `gin_ts2` child of the recorded `timeout` PID.
  - Rank 1: the `gin_ts2` child of the recorded remote PID, and only if that PID's command line carries the trial's
    unique tag. Cleanup uses the same rule.
  - Leftovers are counted with a pattern that does not match its own shell.
  - No `pkill` or `killall` anywhere. Every kill record names a PID.
- **Time bounds** `[소스, 측정]`.
  - Each rank runs under `timeout -s KILL WATCHDOG_S+20` plus the driver's own watchdog thread.
  - ssh and scp are bounded only by the hold's `timeout -s KILL 880`.
  - Holds lasted 33–625 s.
- **Columns** `[소스]`.
  - Every column of section 3.1 exists in `rows_hd.py` or the shared extractors, with the stated meaning.
  - The extractors' output names do not collide. The one shared name, `n_mute_on_r0`, is computed with the same pattern in
    `rows_extra.py` and `rows_ow.py`.
  - The regular expressions match the real lines: no rule failed for lack of a match, and I checked samples of the
    decline, round-start, plan-rejection, watchdog and classifier lines.
- **Exclusions** `[소스]`. `status_of` implements section 8 rule for rule:
  - bind;
  - the hook sets (rank 0, rank 1, both; `hd_ref2_f1_b` was removed before the tag, as recorded);
  - the kill sets;
  - the three order rules;
  - the mute;
  - the responder rejection;
  - the firmware overrun on `hd` and `hdp` outside `hd_fwslow_f1_b@hd`.

  The configuration checks also match section 8. The only gap is that `stk` does not test that the abort-word line is
  absent.
- **Rules that could pass on empty data** `[소스]`.
  - In the shared grammar an empty field compares false. Arithmetic on it makes the condition false, and an unknown
    column name raises an error, so a typo cannot pass silently.
  - Every rule that predicts an absence has a positive term in the same `count`: B1, B4, B11, D1, R2, R6–R11, P6, P7, T3.
    The one exception is A4's `or` branch (L1).
  - `n_notrts` is empty, not 0, when a rank has no QP state line.
- **Clock conversion** `[소스]`.
  - rank 0's `clock_offset_ms` (rank 1 clock − rank 0 clock, best of 32 round trips) is applied in the right direction:
    `+off` for rank 0 kills and `−off` for rank 1 kills (`rows_hd.py` 268–277).

## Nits

- `onAlarm` (201–206) prints "abort did not return" even when the shrink alarm (1129) or the child-destroy alarm (1162)
  fires.
- In shrink mode `post_abort_kernel_running_at_abort_return` is measured after the first post-abort wait (180–196), so
  the name no longer fits. rank 0's `kernel_ms` also includes the shrink and the 3 s wait, because `tEnd` is reset at 1173.
  No rule uses either value.
- `../scripts/ts2/rows.py` 156–158 treats every kill as a rank-1 kill (`kill − off`), which is wrong for rank-0 kills. No
  rule uses `fault_mono_r0` or `q4_after_fault_ms_r0` in a rank-0 kill cell.
- T3 checks "no recovery and no decline" on rank 0 only. In the data rank 1 has neither: its only release is `why=abort`
  at teardown (3/3). E4 does not check `rs_declined_r1`, which is 0 in 5/5.
- D1 shows "nothing re-posted" through two things: no `recovered` line on either rank, and rank 0's own "nothing
  re-posted" line. There is no receiver-side duplicate check. `plan_rej_init_r0=1` in 10/10.
- `bind_fail` matches only the EADDRINUSE text. Any other failure before NCCL starts (for example a failed rank-1 ssh in a
  non-kill cell) would be scored as a failure. None occurred.
- 3.1 says `fault_after_launch_r0_ms` is measured from the kernel start. The code uses kv `launch_mono_ms`, the host time
  just before the launches.
- `hog_running_at_end` is written to kv but not parsed.
- `cells.sh` 54–56: "rank 1's kernel resets the connection" should say rank 1's TCP stack.
- `hogKernel`'s guard "never true in practice" (682) is true for thread 1 if the loop ran exactly once. It is harmless.
  The stream `s4` and `dSink` are never freed, which does not matter because the process exits.
