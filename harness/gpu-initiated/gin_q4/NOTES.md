# gin_q4: 상세 기록

아래는 예전 README 본문을 그대로 옮긴 것이다(영어). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정**

- TL;DR의 "`ncclCommAbort` returned in every trial"은 보내는 쪽(rank 0)만 맞다. 받는 쪽 abort는 blocking
  F1~F3에서 돌아오지 않았다(N30 90/90, N30 stock 대조 10/10). N30 표의 "abort clean"도 rank 0 기준이다.
- N30(`results/20260925_n30/`)이 GPU doorbell로 돌았다는 것은 두 지표로 추정한 것이다. 이 빌드는 doorbell 모드를 기록하지 않는다.
- N30(`results/20260925_n30/`)은 모두 rain `mlx5_1`의 펌웨어 명령 슬롯 하나가 샌 상태에서 돌았다. 슬롯은 09-25 06:45에
  샜고(`../gin_recovery/TRANSPARENT_S1.md`), N30 Q4 253회는 07:31~09:34에 돌았다. N30 문서에는 이 언급이 없다.
- 이 드라이버에는 받는 쪽이 동기화 응답 뒤에 버퍼를 초기화하는 경쟁이 남아 있다
  (`../gin_recovery/RECOVERY_DESIGN.md` §11). 틀린다면 거짓 불일치 쪽이며, 관찰되지 않았다.

Follow-up to `../gin/` (Q2 for NCCL GIN) and `../nvshmem/` (Q2/Q3 for NVSHMEM IBGDA). Same
cluster and conventions: rank 0 = rain (initiator, Quadro RTX 5000 sm_75, mlx5_1), rank 1 =
sunny (target, RTX A4000 sm_86, mlx5_0), ConnectX-6 (VPI, MT28908) RoCE, GDAKI in its CPU-doorbell
fallback (no PeerMappingOverride, no gdrdrv), CQ in GPU memory, `NCCL_IB_TIMEOUT=14`.

## TL;DR

- **Task A (in-stack A/B).** A collapsed CQ (`cc=1`, GPU memory) inside GIN GDAKI **does receive
  error CQEs**: the device poll returned -EIO in 27/27 fault trials (F1/F2/F3, timeout and
  blocking), as the ring CQ did in 33/33 (F1-F4, Tasks A+B). At poll time slot 0 held the
  **root-cause** CQE (5/0xf5, 10/0x88, 12/0x81) in 27/27; 500 us later it held the trailing
  flush 5/0xf9 of the next WQE (18/18 re-reads), which is Q1's prediction measured on a real
  collapsed CQ. So "the collapsed CQ hides error completions" is **rejected in-stack**;
  NVSHMEM's missing error CQEs have another cause.
- Making the collapsed CQ run at all needed a fix: NCCL + DOCA in CPU-proxy mode **deadlock at
  the first SQ wrap** (64 put+signal) with a collapsed CQ, because DOCA's collapsed blocking
  poll waits on `sq_wqe_pi`, which is only maintained with `CPU_PROXY_UPDATE_PI` (measured,
  root cause from source). `64B_COLLAPSED_HOST` cannot work here: DOCA refuses it without
  GDRCopy and then aborts in its own error path (measured, backtrace kept).
- **Task B (Q4).** With `NCCL_GIN_FAULT_CLASSIFY=1` on the ring CQ, the device classified every
  fault correctly (F1 LOCAL_QP_ERR 5/0xf5, F2 REM_ACCESS 10/0x88, F3 RETRY_EXC 12/0x81; 6/6 each
  over both wait modes; F4 12/0x81, same class as F3). The root cause is found by scanning back
  from the polled index; the polled (trailing, signal) WQE itself always held 5/0xf9.
  `ncclCommGetAsyncError` returns `ncclRemoteError` **~0.19 ms after device detection**
  (median), i.e. 15 ms / 2.8 ms / 3.6-3.7 s / 3.6-3.7 s after the fault for F1/F2/F3/F4, versus
  9.4 / 10.0 / 9.4 / 8.0 s with the flag off (same build; = Q2 stock). The blocking flush now
  returns `ncclRemoteError`: **init_silent_iters 0** in F1-F3 (flag off: 1 in 9/9).
  `ncclCommAbort` returned in every trial of Tasks A and B except the forced `collapsed_host`
  attempt (process aborted in DOCA); no process was left on either node after any trial.
- **Overhead** (no fault): put+signal+flush p50 +0.06-0.10 us at 4 KiB (10.1-10.2 us, <=1%),
  +0.03-0.19 us at 256 KiB (37.3-37.6 us, <=0.5%); 4 KiB p99 +0.1-0.6 us (within run-to-run
  spread); mailbox watcher at 20 us poll costs ~0.05 CPU core.

## Build and deploy

Base: NCCL **v2.32.3-1** (commit `12df1a11afad322be5a204a2db890161cbf8131d`) +
`../gin/gin_fault_inject.diff` (Q2 hook, unchanged) + **`gin_q4_classify.diff`** (this work;
layered, see its header). A separate source copy and build directory were used, so the Q2 build
(`scratchpad/gi/gin/build`) is untouched:

```
cd <nccl v2.32.3-1> && git apply ../gin/gin_fault_inject.diff && git apply gin_q4_classify.diff
make -j32 src.build CUDA_HOME=/usr/local/cuda-12.8 BUILDDIR=<scratch>/gi/gin_q4/build \
     NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
scripts/build_driver.sh      # gin_q4.cu -> <scratch>/gi/gin_q4/gin_q4 (-Wall -Wextra -Werror clean)
```

Verified: the two diffs applied in order to a pristine `git archive v2.32.3-1` reproduce the
build tree exactly.

Provenance (md5 of the deployed files): the final patch = build **b2** (`libnccl.so.2.32.3`
`4199aa16...`, driver `361d6b7c...`), used for every run except: Task A `A-timeout` (24 trials)
and `diag/collapsed_fix*` ran on **b1** (`dbe98385...` / `3150925c...`), which lacks only the
optional slot re-read (`NCCL_GIN_Q4_LATE_READ_US`, off in those runs; record layout otherwise
identical); `smoke/` and `diag/collapsed_stall*` ran before the collapsed-CQ fix (that is what
they document). Deployed to `~/gi-bundle/gin_q4/` on both nodes (`libnccl.so.2.32.3` +
`gin_q4`, md5 checked; runs use `LD_LIBRARY_PATH` to it). The GIN device API is header-only, so
the driver must be compiled against the Q4 headers.

## What the patch does (`gin_q4_classify.diff`, +740/-16, all default OFF)

| env | effect |
|---|---|
| `NCCL_GIN_GDAKI_CQ_TYPE=ring` (default) | stock: `DOCA_GPUNETIO_VERBS_CQ_64B` ring CQ |
| `...=collapsed` | `DOCA_GPUNETIO_VERBS_CQ_64B_COLLAPSED` + `cq_collapsed=1` for all GDAKI QPs. The device poll already dispatches on `cq->cq_type` at run time (`doca_gpu_dev_verbs_poll_one_cq_at` -> `..._collapsed_at`). Adds `CPU_PROXY_UPDATE_PI` to the put/get code options **for collapsed CQs only** (see Task A). |
| `...=collapsed_host[_force]` | `64B_COLLAPSED_HOST`; refused when `doca_gpu_gdrcopy_is_supported()==0` unless `_force` |
| `NCCL_GIN_FAULT_CLASSIFY=1` | device classification + host mailbox (below) |
| `NCCL_GIN_FAULT_CLASSIFY_POLL_US` | watcher poll period, default 20 us |
| `NCCL_GIN_Q4_QPWATCH_MS` | diagnostic: watcher QUERY_QPs the peer QPs every N ms, logs transitions |
| `NCCL_GIN_Q4_LATE_READ_US` | diagnostic, collapsed: device re-reads slot 0 N us after detection |

**Device (`gin_gdaki.h`).** A new GPU-context field `fault` (nullptr = off) points to a
device control block. Wherever GDAKI polls a CQE — timeout wait (`waitImplCore`), timeout
flush (`flushImplModeCore`), the abort-flag loop, and the **blocking** paths, where
`doca_gpu_dev_verbs_wait` (void) is replaced by the same DOCA blocking poll but keeping its
status — a `-EIO` leads to `q4Report()`: read the CQE with system-scope loads (syndrome byte 55,
vendor_err 54, hw_err 52/53, qpn 57-59, wqe_counter 60-61, op_own 63); on a ring CQ scan
`[cqe_ci, ticket]` for the first current-generation error CQE (the root cause) and count
error/ok CQEs; also count error opcodes in the whole CQ buffer; map (syndrome, vendor) to a
class with the rdma-core table (`providers/mlx5/cq.c`, verified: 0x04 LOC_PROT, 0x05 WR_FLUSH
[0xf5 head-of-SQ local ERR / 0xf9 trailing], 0x12 REM_INV_REQ, 0x13 REM_ACCESS, 0x15 RETRY_EXC,
0x16 RNR_RETRY_EXC, ...); stamp `%globaltimer`; set a per-context sticky error; write one 256-B
record into a host-pinned mapped mailbox (16 slots: invalidate, body with `st.relaxed.sys`,
`__threadfence_system`, `seq`, fence, `magic`) and return `ncclRemoteError` instead of spinning
(timeout) or discarding (blocking). On a device timeout it writes a "timeout dump" record
(polled CQE, window, buffer scan) and returns `ncclTimeout` as before.

**API.** The blocking `ncclGin::flush(coop)` / `wait(req, coop)` now return `ncclResult_t`
(source compatible): after the (void) backend call they query a new
`ncclGinApi_QueryError` (primary template returns `ncclSuccess` for the other backends; GDAKI
reads the sticky word). This is how the blocking path reports the failure.

**Host (`gin_host_gdaki.cc`, `gin_host.cc`).** Per GDAKI context: mailbox
(`ncclCudaHostCalloc`, mapped) + device block, and a watcher thread (sleep `POLL_US`, seqlock
read). On a record it sets the comm's GIN async result to `ncclRemoteError` (pointer handed down
from `ginDevCommSetupWithBackend`) and a flag that `ncclGinGdakiQueryLastError` returns
immediately (bypassing the 10 s throttle), logs one WARN with fingerprint, class, cause and
action (wording of `harness/common/probe.c classify()`), then QUERY_QPs that QP.
Verbatim (ring, F2, `results/20260923/taskB/logs/ring_c1_F2_timeout_t1_r0.log`, prefix trimmed):

```
NCCL WARN GIN/Q4: device-classified error CQE rank=0 seq=1 ctx=0 peer=1 qpn=0x383e wqe=0 path=flush-timeout
  cq=ring fp=10/0x88 syndrome=0x13 hw_err=0/0 class=REM_ACCESS fault=rem_access cause="remote access: invalid
  rkey or out-of-bounds addr" action="refresh rkey / clamp to remote MR bounds, QP-only recover" root_op=0xd
  polled[wqe=1 op=0xd syn=0x5 ve=0xf9] window[err=2 ok=0 root_idx=0 ticket=1 cqe_ci=0] cq_buffer_err=2/128
  gtimer_ns=1790163882115272896 mono_ms=1319042120.365
NCCL WARN GIN/Q4: host QUERY_QP rank=0 qpn=0x383e state=ERR query_us=71 mono_ms=1319042120.481
```

## Driver and method

`gin_q4.cu` = `../gin/gin_fault.cu` + (a) blocking mode keeps the return of `gin.flush()`; an
error return is not counted as a completed iteration (exit 8); (b) `%globaltimer` <->
CLOCK_MONOTONIC calibration at start (a kernel publishes `%globaltimer` to mapped memory; offset
bound from 200k host samples; consistency ~1-2 us); (c) `ncclCommGetAsyncError` polled every
`GIN_ASYNC_POLL_US` (200 us here; Q2 used 2 ms); (d) fault `lat` for the overhead runs; (e) a
device phase marker to locate a kernel that never returns. Fault catalog, lockstep barrier, F2
(put at a 64 MiB offset), F4 (SIGKILL + drain puts), watchdogs: as in Q2.

Teardown timing on both ranks (added 2026-10-06 for `../propagation/`; not yet run on the
cluster): as in `../gin/README.md`. A hung `ncclCommAbort` now prints how long it ran, against
`GIN_ABORT_WATCHDOG_S` or the global deadline, and writes `teardown=hang` to the KV file. The
runner's default `WATCHDOG_S=60` can end a blocking trial during the abort; for a 30 s bound,
raise it.

Times (all on rank 0's CLOCK_MONOTONIC, ms after the fault; fault = hook `fire_mono_ms` for
F1/F3, launch of the first out-of-bounds put for F2, SIGKILL time for F4): `t_dev` = record's
`%globaltimer`, `t_mbx` = watcher read it, `t_rc` = host saw the kernel return (500 us poll),
`t_api` = first non-success `ncclCommGetAsyncError`.

Runs: `scripts/run_matrix.sh <csv> <batch>` inside `../common/cluster_run.sh` (each hold
< 15 min), `scripts/run_trial.sh` per trial (per-trial logs, KV, meta, raw latencies kept),
`scripts/rebuild_csv.py` regenerates each CSV from the logs, `scripts/summarize.py` writes
`results/20260923/summary.md`. 3 trials per fault cell (2 for stock collapsed), 3-6 baselines.
No processes left on either node after any trial (`leftover_procs` = 0 in every row).

## Task A: collapsed vs ring CQ (NCCL_GIN_FAULT_CLASSIFY=1 unless noted)

| CQ | fault | wait | n | -EIO seen | root fp / class | slot / polled CQE at detection | slot 500 us later | t_dev (ms) | t_api (ms) |
|---|---|---|---|---|---|---|---|---|---|
| ring | F1 | timeout | 3 | 3/3 | 5/0xf5 LOCAL_QP_ERR @76 | 5/0xf9 @77 (window: 2 err) | - | 14.6 | 14.9 |
| ring | F2 | timeout | 3 | 3/3 | 10/0x88 REM_ACCESS @0 | 5/0xf9 @1 | - | 2.6 | 2.8 |
| ring | F3 | timeout | 3 | 3/3 | 12/0x81 RETRY_EXC @76 | 5/0xf9 @77 | - | 3592 | 3592 |
| collapsed | F1 | timeout+blocking | 9 | 9/9 | 5/0xf5 LOCAL_QP_ERR | 5/0xf5 @76 (ticket 77) | 5/0xf9 @77 (6/6) | 15.1 | 15.4 |
| collapsed | F2 | timeout+blocking | 9 | 9/9 | 10/0x88 REM_ACCESS | 10/0x88 @0 (ticket 1) | 5/0xf9 @1 (6/6) | 2.5 | 3.2 (b) |
| collapsed | F3 | timeout+blocking | 9 | 9/9 | 12/0x81 RETRY_EXC | 12/0x81 @76 or @74 | 5/0xf9 @77/@75 (6/6) | 3645 | 3646 |
| collapsed, flag off | F1-F3 | timeout | 6 | (not observed) | - | - | - | - | 9402 / 10000 / 9402 |
| collapsed, flag off | F1-F3 | blocking | 6 | (not observed) | - | - | - | - | same; init_silent_iters 1 in 6/6 |
| collapsed_host | none | - | 2 | refused / crashed at init | - | - | - | - | - |

Medians; n=9 pools the 3 plain timeout, 3 timeout-with-re-read and 3 blocking trials. (b) The
500 us slot re-read delays publishing, and so `t_api`, by 0.5 ms in 6 of the 9.
Baselines: ring 3/3, collapsed 3/3 ok (plus 300-iteration collapsed runs in both wait modes
after the fix, `results/20260923/diag/`). The CQ-buffer scan found exactly 1 error entry
(collapsed) / 2 (ring) in every fault trial. Host QUERY_QP at record time: ERR in all fault
trials; the 100 ms QP watch saw ERR at the first sample after the fault for F1/F2 and at
3.6-3.8 s (retry exhaustion) for F3.

Findings:
1. **[measured] Error CQEs are delivered to a collapsed CQ in this stack.** Every fault trial
   produced opcode 0xd in slot 0 with the correct syndrome. The stock (flag off) collapsed runs
   behave exactly like the stock ring: the blocking wait returned although the data never
   arrived (init_silent_iters 1 in 6/6; it can only return on a CQE in the slot, so on the error
   CQE [inferred]), the timeout wait spun to its timeout, and the host learned only at the 10 s
   tick.
2. **[measured + source] Why slot 0 shows the root cause, not a flush.** DOCA's collapsed poll
   (`doca_priv_gpu_dev_verbs_poll_cq_one_collapsed_at`) counts ticket T as complete when the
   slot's `wqe_counter >= T-1` (its code keeps "index+1" in software; NCCL passes the WQE index).
   With put+signal (write @T-1, atomic @T) the poll fires on the write's CQE: in all 27 trials
   the slot's wqe_counter was T-1 and held the root cause; the atomic's flush 5/0xf9 @T
   overwrote it within 500 us (the Q1 gap is ~60 us). With more WQEs behind the failing one the
   slot would already be 5/0xf9 (inferred from Q1 + the re-read). Side effect (from source): on
   a collapsed CQ, NCCL's flush can return when the write has completed but the signal atomic
   has not.
3. **[measured] F1 on GDAKI lands between iterations.** The next put posts WQEs 76/77 to a QP
   already in ERR; the NIC flushes the first with 5/0xf5 and the second with 5/0xf9 (Q1 saw
   0xf5 only for the head WQE at the moment of the ERR; this shows the same for WQEs posted
   afterwards).
4. **[measured] Collapsed CQ + CPU-proxy doorbell deadlocks without `CPU_PROXY_UPDATE_PI`.**
   Before the fix, no-fault runs stopped at iteration 64 (WQE 128 = the QP depth of 128; at
   iteration 128 with `NCCL_GIN_GDAKI_QP_DEPTH=256`) inside `put` (phase marker 1), with the
   flag on or off; the kernel never
   returned and teardown hung. [source] The SQ-slot wait at the wrap uses DOCA's collapsed
   blocking poll, which first spins `while (qp->sq_wqe_pi < cons_index)`; in CPU_PROXY mode
   `submit_proxy` updates `sq_wqe_pi` only with `DOCA_GPUNETIO_VERBS_GPU_CODE_OPT_CPU_PROXY_UPDATE_PI`,
   which NCCL never passes (the ring poll never looks at `sq_wqe_pi`). The same spin would hang
   the stock blocking wait on its first flush. With the option set for collapsed CQs only, 300
   iterations ran in both wait modes.
5. **[measured] `64B_COLLAPSED_HOST` cannot run here.** DOCA: `doca_gpu_verbs_export_qp():
   Host-collapsed CQ type is not supported without GDRCopy` (`gdr_open` fails: no gdrdrv); its
   error path then aborts with `free(): invalid pointer` in `destroy_umem_hl` (it `free()`s the
   `cudaHostAlloc`'d CQ umem) — `results/20260923/diag/collapsed_host_force_*`. The knob
   therefore refuses it unless forced.
6. **[inferred] Consequence for NVSHMEM.** Same NICs, same cc=1 GPU-memory CQ, same faults: here
   the error CQE is written; in NVSHMEM IBGDA it never was (1024-entry scans, even with the QP
   in ERR). So the absence there is not a property of collapsed CQs; the cause lies in how
   NVSHMEM creates/drives its QP/CQ or its proxy (not identified; e.g. compare its CQ context
   via QUERY_CQ and whether its proxy stops ringing after ERR).

## Task B (Q4): ring CQ, flag on vs off (same build)

| fault | wait | flag | n | device rc | class (true) | root fp | t_dev | t_mbx | t_api (ms) | init_silent_iters | init / target |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | timeout | on | 3 | ncclRemoteError | LOCAL_QP_ERR (F1) | 5/0xf5 | 14.94 | 15.02 | **15.18** | 0,0,0 | error / timeout |
| F1 | blocking | on | 3 | ncclRemoteError | LOCAL_QP_ERR | 5/0xf5 | 15.56 | 15.62 | **15.66** | **0,0,0** | error / hang |
| F2 | timeout | on | 3 | ncclRemoteError | REM_ACCESS (F2) | 10/0x88 | 2.62 | 2.69 | **2.79** | 0,0,0 | error / timeout |
| F2 | blocking | on | 3 | ncclRemoteError | REM_ACCESS | 10/0x88 | 2.58 | 2.64 | **2.79** | **0,0,0** | error / hang |
| F3 | timeout | on | 3 | ncclRemoteError | RETRY_EXC (F3) | 12/0x81 | 3637.7 | 3637.8 | **3637.9** | 0,0,0 | error / timeout |
| F3 | blocking | on | 3 | ncclRemoteError | RETRY_EXC | 12/0x81 | 3698.1 | 3698.2 | **3698.3** | **0,0,0** | error / hang |
| F4 | timeout | on | 3 | ncclRemoteError | RETRY_EXC (F4) | 12/0x81 | 3701.7 | 3701.9 | **3701.9** | 0,0,0 | error / killed |
| F4 | blocking* | on | 3 | ncclRemoteError | RETRY_EXC | 12/0x81 | 3643.1 | 3643.2 | **3643.2** | 0,1,0 | error / killed |
| F1 / F2 / F3 | timeout | off | 3+3+3 | ncclTimeout | - | - | - | - | 9401 / 10000 / 9402 | 0 | timeout / timeout |
| F1 / F2 / F3 | blocking | off | 3+3+3 | (success) | - | - | - | - | 9401 / 10000 / 9402 | **1,1,1 each** | ok / hang |
| F4 | both | off | 6 | ncclTimeout | - | - | - | - | 8038-8039 | 0 | timeout / killed |

Medians over 3 trials (full ranges and all columns in `results/20260923/summary.md`). *F4 uses
the timeout-mode drain in both modes (as in Q2). Baselines (3 timeout + 3 blocking, flag on):
all ok, no records.

- **Detection.** The device sees the fault at the first poll that meets the error CQE: F1 at the
  next iteration's flush (~15 ms = the 15 ms iteration gap), F2 2.6 ms after the out-of-bounds
  put was launched, F3/F4 at RETRY_EXC (3.5-3.8 s at IB timeout 14, cf. Q1 3.52-3.61 s and GIN
  proxy F3 3.6 s).
- **Device -> host.** Record read by the watcher 94 us after `t_dev` (median, 56-126, n=33 ring
  trials; the 20 us sleep overshoots to ~60-80 us), `ncclCommGetAsyncError` 190 us (69-371; the
  driver polls every 200 us), kernel return seen by the host 372 us (500 us poll). With the flag
  off the host learns only at the next 10 s QP-state tick (8.0-10.0 s here, phase-dependent).
- **Class vs truth.** F1, F2, F3 exact in 6/6 each. F4 (SIGKILL) gives RETRY_EXC 12/0x81 like
  F3 (on GDAKI the killed peer's QPs vanish and packets are dropped; the GIN proxy saw REM_ACCESS
  10/0x88 at 60 ms in Q2); separating peer_err from proc_kill needs a liveness probe, as in the
  CPU harness.
- **Trailing WQE.** The polled index is the signal atomic, whose CQE was 5/0xf9 in every ring
  fault trial; the root cause sits one index earlier and is found by the window scan
  (window = 2 error CQEs, 0 ok). A device that only read the polled CQE would report
  FLUSH_TRAILING for every fault.
- **Silent success.** Flag on: the blocking flush returns `ncclRemoteError`, the iteration is
  not counted, `init_silent_iters` 0 in 9/9 F1-F3 blocking trials (flag off: 1 in 9/9). The one
  F4 value of 1 is not a silent success: the flush of iteration 177 completed (ACKed) and rank 1
  was killed before it logged that iteration; the following drain flush returned
  `ncclRemoteError` (12/0x81).
- **Teardown.** `ncclCommAbort` returned on rank 0 in every trial (the target's blocking hang is
  bounded by the driver cap, as in Q2).

## Overhead (no fault, ring CQ, same build; `results/20260923/lat/`)

5 x 2000 put+signal+flush per run, timed per iteration on the GPU, 4 runs per cell (40k
samples), flag off/on interleaved; plus 2 runs with a 1 ms watcher poll.

| bytes | wait | off p50 / p99 (us) | on (20 us poll) p50 / p99 | on (1 ms poll) p50 / p99 | CPU (cores, off / on 20 us / on 1 ms) |
|---|---|---|---|---|---|
| 4096 | timeout | 10.11 / 10.78 | 10.21 / 11.39 | 10.21 / 11.26 | 2.02 / 2.08 / 2.03 |
| 4096 | blocking | 10.21 / 11.36 | 10.27 / 11.46 | 10.27 / 11.46 | 2.02 / 2.07 / 2.03 |
| 262144 | timeout | 37.31 / 38.94 | 37.34 / 38.94 | 37.47 / 38.94 | 2.02 / 2.07 / 2.02 |
| 262144 | blocking | 37.38 / 38.94 | 37.57 / 39.01 | 38.02 / 38.94 | 2.02 / 2.07 / 2.02 |

p50 cost <= 0.1 us (<= 1%) at 4 KiB; the 256 KiB differences (<= 0.6 us) are inside the
per-run spread (36.9-37.8 us). The 4 KiB p99 shift (+0.1-0.6 us) persists with a 1 ms watcher
poll, so it is not the watcher thread [measured]; it presumably comes from the device-side
change (extra branches, larger kernel) [inferred, not isolated]. The watcher itself costs ~0.05
CPU core at a 20 us poll, ~0.01 at 1 ms. The ~2 cores baseline is the GIN CPU-proxy doorbell
thread (spinning) plus the async-error poller.

## Measured vs inferred

Measured: everything in the tables; CQE bytes read by device code; slot re-read; the stall
point and phase of the collapsed deadlock and its disappearance with `CPU_PROXY_UPDATE_PI`;
the DOCA refusal message and backtrace for `collapsed_host`; QUERY_QP states; overheads.
From source (read, consistent with the measurements): why the collapsed poll deadlocks
(`sq_wqe_pi`), why slot 0 held the root cause (DOCA's `wqe_counter >= T-1` rule), the early
flush return on collapsed CQs. Inferred: slot content for batches with more WQEs behind the
failure (would be 5/0xf9); the cause of the missing CQEs in NVSHMEM (not collapse, otherwise
unknown); the source of the small p99 shift.

## Limitations

- CPU-doorbell fallback only (no PeerMappingOverride/gdrdrv); the device CQ paths are the ones
  a GPU-doorbell system runs, but doorbell timing differs and `COLLAPSED_HOST` is untestable.
- One op shape (put 256 KiB + signal, then flush; 2 WQEs per iteration); F1 always lands between
  iterations, so a root cause behind many outstanding WQEs was not exercised on the GPU. The
  collapsed-CQ root-cause visibility depends on DOCA's off-by-one and on the 2-WQE shape.
- Collapsed runs needed the `CPU_PROXY_UPDATE_PI` fix; stock NCCL cannot use a collapsed CQ in
  this mode at all.
- The blocking API change is to the C++ `ncclGin` methods; the C entry points (`ncclGinFlush`,
  `ncclGinWait`) still return void. The sticky error is per GIN context, not per peer.
  Classification covers GDAKI only (proxy/GPI/EFA return `ncclSuccess` from the new query).
- The target (rank 1) never sees an error on GDAKI (it posts nothing); its blocking waitSignal
  still hangs until the host cap. Recovery (QP reset, replay) is not attempted.
- 3 trials per cell (2 for stock collapsed); F4 timing depends on the kill landing mid-run.

## Files

| path | what |
|---|---|
| `gin_q4_classify.diff` | the Q4 patch (layered on `../gin/gin_fault_inject.diff`) |
| `gin_q4.cu` | driver (from `../gin/gin_fault.cu`) |
| `scripts/build_driver.sh` | builds the driver against the Q4 build tree |
| `scripts/run_trial.sh`, `run_matrix.sh` | one trial / one batch (run inside `../common/cluster_run.sh`) |
| `scripts/q4_row.py`, `rebuild_csv.py`, `summarize.py` | CSV row, CSV regeneration from logs, tables |
| `results/20260923/taskA/` | Task A: 56 trials (`taskA.csv`, `logs/`) |
| `results/20260923/taskB/` | Task B: 54 trials, flag on + off |
| `results/20260923/lat/` | overhead: 40 runs, raw per-iteration latencies (`*_lat_raw.csv.gz`) |
| `results/20260923/diag/` | collapsed stall/fix runs, `collapsed_host` backtrace and DOCA log |
| `results/20260923/smoke/` | first smoke runs (collapsed before the fix) |
| `results/20260923/summary.md` | all tables with ranges |

Reproduce (each line one cluster hold):

```
CR=../common/cluster_run.sh; R=results/20260923
$CR -t q4A -- bash scripts/run_matrix.sh $R/taskA/a.csv A-timeout 3      # also A-late, A-blocking, A-stock, A-host
$CR -t q4B -- bash scripts/run_matrix.sh $R/taskB/b.csv B-on-timeout 3   # also B-on-blocking, B-off-timeout, B-off-blocking
$CR -t q4L -- bash scripts/run_matrix.sh $R/lat/l.csv lat 1              # LAT_REP_FROM/TO for more reps; lat-poll
for d in taskA taskB lat; do python3 scripts/rebuild_csv.py $R/$d/logs $R/$d/$d.csv; done
python3 scripts/summarize.py $R
```
