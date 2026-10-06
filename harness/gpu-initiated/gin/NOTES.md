# gin: 상세 기록

아래는 예전 README 본문을 그대로 옮긴 것이다(영어). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정**

- "GDAKI teardown returned in all cells"는 보내는 쪽(rank 0)만 맞다. 받는 쪽(rank 1)의 abort는 GDAKI
  blocking F1~F3 9/9회 돌아오지 않았다. 결과 표의 teardown "clean"도 rank 0 기준이다.
- 받는 쪽은 두 backend 모두 F1~F3 18/18회 비동기 오류를 받지 못했다. 자기 QP가 ERR인 F3에서도 같았다.
  "호스트가 10 s마다 QP 상태를 검사한다"는 설명은 rank 1에는 맞지 않는다. 원인은 확인하지 않았다.
- "F2 regimes"의 MR 안쪽 넘침 "silent loss"는 남아 있는 원시 데이터가 없다. v1의 F2 행은 모두
  REM_ACCESS(proxy)나 10 s 검사(GDAKI)로 나온다.
- F4는 두 대기 방식 모두 timeout 대기로 끝을 확인했다. "F4 blocking" 행은 사실상 timeout 행이다.
- stock GDAKI 장치가 오류 CQE를 -EIO로 받고 버린다는 설명은 소스 근거다. stock 빌드에서 직접 관찰하지 않았다.
- proxy와 GDAKI의 F2~F4 칸은 3회씩이며 N30으로 다시 재지 않았다. proxy F4의 10/0x88(6/6)은
  `../../teardown_order/`에 따르면 경쟁 조건이라 12/0x81도 나올 수 있다.

Answers the **per-stack fault measurement** of the GPU-initiated RDMA fault study (see
`../DESIGN.md`) for NCCL GIN on both networking backends we can run here: the **CPU-proxy** backend
and the **GDAKI** (DOCA GPUNetIO) backend. For each fault we measure which layer notices, whether
the CQE error code (`ibv_wc_status`/`vendor_err`) is visible anywhere, whether the device wait times
out / hangs / falsely reports success, whether the delivered bytes are intact, how long until the
host learns (via `ncclCommGetAsyncError`), and whether teardown (`ncclCommAbort`) returns.

Cluster: **rain** = rank 0 / initiator (Quadro RTX 5000, sm_75, mlx5_1, GID 4),
**sunny** = rank 1 / target (RTX A4000, sm_86, mlx5_0, GID 3), ConnectX-6 (VPI, MT28908) RoCE,
no `PeerMappingOverride`, no `gdrdrv`.

## Build

NCCL **v2.32.3-1** (tag `v2.32.3-1`, commit `12df1a11afad322be5a204a2db890161cbf8131d`)
built from source with CUDA 12.8 for sm_75 + sm_86:

```
make -j src.build CUDA_HOME=/usr/local/cuda-12.8 \
     NVCC_GENCODE="-gencode=arch=compute_75,code=sm_75 -gencode=arch=compute_86,code=sm_86"
```

GIN and both backends are enabled by the default Linux build
(`makefiles/common.mk`: `NCCL_GIN_PROXY_ENABLE=1`, `NCCL_GIN_GDAKI_ENABLE=1` for
CUDA>=12.2 & sm>=70; the DOCA GPUNetIO device library ships in-tree under
`src/transport/net_ib/gdaki/doca-gpunetio` and is compiled with
`-DDOCA_GPUNETIO_USE_CUDA_WRAPPER -DDOCA_VERBS_USE_NET_WRAPPER`). No extra flags
were needed. The library is deployed to sunny at `~/gi-bundle/gin/`
(`libnccl.so.2.32.3` + `gin_fault`); runs load it via `LD_LIBRARY_PATH`.

`scripts/build_driver.sh` builds the driver against this tree.

## Backend selection

`NCCL_GIN_TYPE=2` forces the **proxy** backend, `NCCL_GIN_TYPE=3` forces **GDAKI**
(`include/nccl_device/core.h`: `NCCL_GIN_TYPE_PROXY=2`, `NCCL_GIN_TYPE_GDAKI=3`;
default priority is GDAKI > Proxy). Both initialize on this hardware:

* proxy (`gin_type=2`): standard NCCL IB QPs; the CPU progress thread posts the
  WRs and polls the CQ with `ibv_poll_cq`.
* GDAKI (`gin_type=3`): `preHopper=1 dataDirectNic=0 mcst=1`, `reliable_db=disabled`.
  Because there is no `PeerMappingOverride`, DOCA cannot map the doorbell to the
  GPU, so it falls back to a **CPU thread ringing the doorbell** (`needsProxyProgress`),
  while the **CQ stays in GPU memory** and the GPU thread polls it. GDAKI ran fine
  in this fallback mode; no system changes were needed.

### GDAKI CQ shape (for cross-reference with the CQE-sequence question)

NCCL's GDAKI init (`gin_host_gdaki.cc`) zero-initializes `doca_gpu_verbs_qp_init_attr_hl`
and never sets `cq_collapsed`, so `resolve_cq_type()` yields
`DOCA_GPUNETIO_VERBS_CQ_64B` — a **normal ring CQ** (size = `sq_nwqe` =
`NCCL_GIN_GDAKI_QP_DEPTH`, default 128), **not** a single-slot collapsed CQ.
`doca_gpu_dev_verbs_poll_one_cq_at` indexes it per-WQE
(`idx = (cons_index + cqe_rsvd) & (cqe_num-1)`), polling the CQE for the exact
WQE being waited on. So, unlike NVSHMEM IBGDA's collapsed 1-slot CQ, the
root-cause error CQE is preserved at its ring slot. **However**, the device poll
only reads the *opcode* and returns `-EIO` when it is `REQ_ERR`; it never reads
`syndrome`/`vendor_err` unless `DOCA_GPUNETIO_VERBS_ENABLE_DEBUG` is compiled in,
and the host-side `doca_gpu_verbs_query_last_error` reads only the **QP state**
(a boolean `has_error`), not the CQE. So neither the root-cause nor the flush
error code (5 / 0xf9) is exposed by GDAKI in a production build — the device
sees "some REQ_ERR", the host sees "QP is in ERR", and the syndrome is discarded.

## Fault-injection patch

`gin_fault_inject.diff` (against v2.32.3-1, 3 files, +161/-1) adds an
**env-gated, default-off** test hook:

* `NCCL_GIN_FAULT_INJECT=local_err:<ms>` or `peer_err:<ms>` — a detached host
  thread waits `<ms>` after the GIN context of the **user** devComm is created
  (inside `ncclDevCommCreate`, just before the first device GIN op), moves **this
  rank's peer-connected** GIN QPs of the **backend in use** to ERR, and logs
  `fire_mono_ms` / `done_mono_ms` on CLOCK_MONOTONIC. Both tokens do the same
  thing; the fault class depends only on the rank it is set on (initiator = F1
  `local_err`; target = F3 `peer_err`).
  * gating (`src/gin/gin_host.cc`): a thread-local `ncclGinFaultUserCtx` is true
    only while the GIN contexts of a devComm without an abort flag (= a user
    devComm; NCCL's internal symmetric-kernel devComm has one) are created. Both
    hooks arm only then. The host-RMA proxy never passes through this code.
  * proxy (`src/transport/net_ib/gin.cc`): `ibv_modify_qp(IBV_QPS_ERR)` on the RMA
    send *and* recv QPs to the peer (recv QPs matter for the target side: they
    receive the peer's writes). Here: 4 GIN contexts x (send+recv) = **8 QPs**.
  * GDAKI (`src/transport/net_ib/gdaki/gin_host_gdaki.cc`):
    `doca_verbs_qp_modify(..., DOCA_VERBS_QP_STATE_ERR)` (mlx5 `QP_2ERR`) on the
    QPs to other ranks. Here: 4 contexts x 1 peer = **4 QPs** (of 12 main QPs per
    devComm: 4 to the peer, 4 to self, 4 self-loop responders; no companion QPs
    since no counters are requested).

*Why "proxy" QPs exist in a GDAKI run (QA item 2):* window registration
(`ncclCommWindowRegister` -> `symMemoryRegisterRma` -> `ncclRmaProxyConnectOnce`)
brings up NCCL's **host-RMA proxy** (the host-side RMA API) independently of the
GIN backend; it uses the same RMA-IB-proxy code (`ncclRmaIbProxyCreateContext`),
here with `rmaProxyCtxCount=1`. The v1 hook lived in that function unconditionally,
so in GDAKI runs it also moved those 2 idle host-RMA QPs (send+recv) to ERR, and in
proxy runs it additionally moved the internal devComm's 4+4 GIN QPs. v2 gates both
hooks as above; v2 logs show exactly one armed hook per rank per run. For scale
(INFO logs, rank 0): a GDAKI run creates 24 GDAKI QPs (2 devComms x 12) plus 8
plain IB-verbs connections (host-RMA proxy + GIN out-of-band control); a proxy run
shows 40 `ncclIbConnectImpl` connections.

The hook is inert unless the env var is set, so the stock path is unchanged.
When the var is absent the library behaves exactly as upstream.

**F2 (`rem_access`)** needs no patch: the driver `put`s at `dstOffset = 64 MiB`,
far outside the registered remote MR. (A put just past the logical window but
within the page-rounded MR raises no error — see Observations — so a small
overrun is not enough.) The GIN device `put` does not bounds-check the offset, so
the NIC raises REM_ACCESS.

**F4 (`proc_kill`)** needs no NCCL patch: the runner SIGKILLs rank 1 by PID
mid-run; the driver keeps the lockstep barrier and, on peer death, drains extra
puts to the dead peer so the RDMA fault surfaces on the initiator.

## Driver

`gin_fault.cu` — a 2-rank driver (rank 0 on rain, rank 1 on sunny, one GPU each):

* Bootstrap: rank 0 ships the `ncclUniqueId` over our own TCP socket on the
  management network (eno1, 192.0.2.193/.194). NCCL's own bootstrap is pinned
  to eno1 with `NCCL_SOCKET_IFNAME=eno1` so it never rides the RoCE link that
  carries the user's NVMe-oF storage. The GIN data path uses
  `NCCL_IB_HCA=mlx5_1` (rain) / `mlx5_0` (sunny); GID index is probed per node.
* Uses the 2.32 device API: `ncclMemAlloc` symmetric memory,
  `ncclCommWindowRegister`, `ncclDevCommCreate` (with `ginConnectionType=FULL`,
  `ginSignalCount=1`), and a kernel that calls `gin.put(..., ncclGin_WeakSignalInc)`
  + `gin.flush` on the initiator and `gin.waitSignal` on the target.
* Per iteration `i`: rank 0 fills M bytes (default 256 KiB) with a per-(i,byte)
  pattern, `put`s + signals into rank 1's window, and `flush`es (local completion);
  rank 1 poisons its receive buffer (0xA5), `waitSignal`s for the i-th increment,
  then byte-compares every byte (ok / mismatch / missing). A management-net TCP
  barrier keeps the two ranks in lockstep so the fault lands mid-run.
* Two wait modes: `timeout` uses the device API's `*Timeout` variants (bounded on
  the GPU with `clock64`); `blocking` uses the plain unbounded waits (bounded only
  by a host watchdog that records the hang and kills the process).
* A background thread polls `ncclCommGetAsyncError` every 2 ms and records the
  first non-success result and its CLOCK_MONOTONIC time. After any abnormal end
  (device timeout, hang, peer loss) the host **keeps polling for up to 15 s**
  (`GIN_POST_POLL_S`) before teardown, so slow host-side detectors (GDAKI's 10 s
  QP-state check) are observed. Then it tears down under an alarm watchdog
  (`ncclCommAbort`) and records whether abort returned.
* Teardown timing, both ranks (added 2026-10-06 for `../propagation/`; not yet run on the
  cluster). A returned abort prints `[rankN] ncclCommAbort returned <ret> after X ms`
  (KV `teardown=clean teardown_ms=X`), as before. A hung abort now also prints
  `[rankN] ncclCommAbort did not return within S s` after the unchanged `WATCHDOG` line
  (KV `teardown=hang teardown_bound_s=S`). `S` is `GIN_ABORT_WATCHDOG_S`, 15 by default;
  `scripts/run_trial.sh` now takes it from the environment. If the global deadline cuts a
  running abort first, the driver prints `... did not return within X ms (global watchdog)`
  (KV `teardown=hang teardown_ms=X teardown_cut_by=global_watchdog`). For a 30 s bound, set
  `GIN_ABORT_WATCHDOG_S=30` and raise `WATCHDOG_S` so the global deadline comes later.
* Timing (QA item 1): each rank logs its start `t0_mono_ms`; right after the
  unique-id exchange rank 0 measures the rain<->sunny CLOCK_MONOTONIC offset
  (32-round ping-pong on the management socket, min-RTT sample; RTT ~0.2 ms).
  Fault fire time: F1/F3 = the hook's `fire_mono_ms` (F3 on sunny, converted);
  F2 = rank 0's launch of the first out-of-bounds put; F4 = a timestamp taken on
  sunny **in the same process that sends SIGKILL** (python `clock_gettime` then
  `os.kill`), converted to rain's clock with the offset. `fault_ms` and
  `host_error_ms` are relative to rank 0's start; **`surface_ms = host_error_ms -
  fault_ms`**; `surface_by` says which rank's `ncclCommGetAsyncError` saw it first.
* `init_silent_iters` (QA item 4) = rank 0 okIters - rank 1 okIters: iterations
  the initiator reported complete whose data rank 1 never received intact. Both
  ranks log `okit=N` per iteration so the value survives a SIGKILL.
* Blocking-mode per-op cap `GIN_BLOCK_CAP_S` (default 25 s).
* Comm is **blocking** by default (the shipped GIN example's pattern; non-blocking
  symmetric-window registration was unreliable in this build — it tripped
  `ncclCommEnsureReady` "comm not ready"); abort is bounded by the alarm watchdog
  instead. `GIN_NONBLOCKING=1` forces a non-blocking comm.

Exit codes: 0 ok, 1 usage/setup, 2 NCCL error, 3 async NCCL error, 4 device wait
timeout, 5 data mismatch/missing, 6 CUDA error, 7 watchdog (hang).

## Running

Every cluster run goes through `../common/cluster_run.sh` (cluster lock + idle-link
wait). `scripts/run_trial.sh` runs one trial (launches rank 1 on sunny over SSH,
rank 0 on rain, injects the fault, merges both ranks' KEY=VALUE outputs into one
CSV row). `scripts/run_matrix.sh <backend> <csv> <batch>` runs a batch of trials
(`baseline`, `faults-timeout`, `faults-blocking`); the caller wraps each batch in
one `cluster_run.sh` hold (<~15 min each, released between batches).
`scripts/merge_v2.py` assembles the final CSV (v1 baseline + v2 faults + refs) and
`scripts/summarize.py` collapses it into the table below.

```
CR=../common/cluster_run.sh
for be in proxy gdaki; do for b in faults-timeout faults-blocking; do
  $CR -t gin-$be-$b -- bash scripts/run_matrix.sh $be results/20260923/v2/gin_faults_v2.csv $b; done; done
python3 scripts/merge_v2.py results/20260923 && python3 scripts/summarize.py results/20260923/gin_results.csv
```

## Results

Final data: `results/20260923/gin_results.csv` (73 rows) and `summary.md`:
baseline from the v1 matrix (unaffected by the QA fixes), all F1-F4 cells from the
**v2 re-run** (`results/20260923/v2/`, 48 trials, 3 per cell, NCCL_IB_TIMEOUT=14,
post-fault polling, gated hooks, CLOCK_MONOTONIC fault times), plus the IB=20
references in `results/20260923/ref60/` (the lead's proxy re-measurement and one
GDAKI blocking trial). **Superseded:** `gin_results_v1.csv` / `summary_v1.md` —
their `host_error_ms` is relative to program start (not a time-to-surface), GDAKI
timeout "host never learns" was a driver artifact (process exited ~5 s after the
fault), and the old `ref` rows had a 5 s device cap (the ">55 s" claim was wrong).

`surface_ms` = host time-to-surface after the fault fired, median [min-max] over
trials; `init_silent_iters` per trial; `status/ve` from the proxy WARN.

| backend | fault | wait | n | init / target | data | init_silent_iters | host_error | surface_ms | fp_where | status/ve | teardown |
|---|---|---|---|---|---|---|---|---|---|---|---|
| proxy | none | both | 5+5 | ok / ok | ok | 0 | none | - | none | - | clean |
| proxy | F1 | timeout | 3 | timeout / timeout | missing | 0,0,0 | remote | **7** [6-8] | log | 5/0xf5 | clean |
| proxy | F1 | blocking | 3 | hang / hang | n/a | 0,0,0 | remote | **9** [8-11] | log | 5/0xf5 | **hang** |
| proxy | F2 | timeout | 3 | timeout / timeout | missing | 0,0,0 | remote | **3** [3-3] | log | 10/0x88 | clean |
| proxy | F2 | blocking | 3 | hang / hang | n/a | 0,0,0 | remote | **3** [3-3] | log | 10/0x88 | **hang** |
| proxy | F3 | timeout | 3 | timeout / timeout | missing | 0,0,0 | remote | **3616** [3578-3654] | log | 12/0x81 | clean |
| proxy | F3 | blocking | 3 | hang / hang | n/a | 0,0,0 | remote | **3613** [3539-3696] | log | 12/0x81 | **hang** |
| proxy | F4 | timeout | 3 | error / killed | missing | 0,0,0 | remote | **60** [60-61] | log | 10/0x88 | clean |
| proxy | F4 | blocking | 3 | error / killed | missing | 0,0,0 | remote | **61** [60-62] | log | 10/0x88 | clean |
| proxy | F3 ref IB=20 | timeout | 2 | timeout / timeout | missing | 0,0 | remote | ~57170 (est) | log | 12/0x81 | clean |
| proxy | F3 ref IB=20 | blocking | 2 | hang / hang | n/a | 0,0 | remote | ~58074 (est) | log | 12/0x81 | hang |
| gdaki | none | both | 5+5 | ok / ok | ok | 0 | none | - | none | - | clean |
| gdaki | F1 | timeout | 3 | timeout / timeout | missing | 0,0,0 | remote | **9402** [9401-9403] | api | - | clean |
| gdaki | F1 | blocking | 3 | **ok** / hang | n/a | **1,1,1** | remote | **9402** [9401-9403] | api | - | clean |
| gdaki | F2 | timeout | 3 | timeout / timeout | missing | 0,0,0 | remote | **10000** [10000-10001] | api | - | clean |
| gdaki | F2 | blocking | 3 | **ok** / hang | n/a | **1,1,1** | remote | **10000** [10000-10000] | api | - | clean |
| gdaki | F3 | timeout | 3 | timeout / timeout | missing | 0,0,0 | remote | **9402** [9402-9403] | api | - | clean |
| gdaki | F3 | blocking | 3 | **ok** / hang | n/a | **1,1,1** | remote | **9403** [9402-9403] | api | - | clean |
| gdaki | F4 | timeout | 3 | timeout / killed | missing | 0,0,0 | remote | **8019** [8004-8022] | api | - | clean |
| gdaki | F4 | blocking | 3 | timeout / killed | missing | 0,0,0 | remote | **8008** [8007-8041] | api | - | clean |
| gdaki | F3 ref IB=20 | blocking | 1 | **ok** / hang | n/a | **1** | remote | **59407** | api | - | clean |

"hang" = `hang_killed` (bounded by the host cap/watchdog). All host errors were
first seen on rank 0 (`surface_by=r0`). The lead's IB=20 proxy rows were measured
with the older driver (no CLOCK_MONOTONIC stamps); their `surface_ms` is estimated
as host_error_ms minus the v2 median F3 fire time (1297 ms) and matches the lead's
direct measurement from WARN timestamps (fault -> WARN 57 s timeout, 58-59 s
blocking).

## Observations

- **Proxy exposes the full status/vendor_err pair, fast.** The progress thread's `ibv_poll_cq`
  WARN carries `status`/`vendor_err` and `ncclCommGetAsyncError` returns
  `ncclRemoteError` (`fp_where`=`log`): F1 WR_FLUSH 5/0xf5 in **~7 ms**, F2 REM_ACCESS
  10/0x88 in **~3 ms**, F4 REM_ACCESS 10/0x88 **~60 ms** after the SIGKILL, F3
  RETRY_EXC 12/0x81 after **~3.6 s** at IB_TIMEOUT=14 (the RETRY_EXC floor; v1's
  "~5 s" was start-relative) and **~57-59 s** at the default IB_TIMEOUT=20.
- **GDAKI exposes no error code and learns only on a 10 s tick.** The device
  poll reads only the CQE opcode (REQ_ERR -> `-EIO`); the host learns via
  `ncclCommGetAsyncError`'s QP-state check (`fp_where`=`api`, "GIN Error detected", no
  status/vendor_err), throttled to NCCL_GIN_ERROR_QUERY_SEC=10 s. In all 24 GDAKI
  fault trials the host error lands at the same moment, **~10.7 s after rank 0's
  start** (60.7 s for the IB=20 ref) — the first throttled query after the initial
  one — regardless of when the fault fired (F2 at 0.7 s -> surface 10.0 s, F1/F3 at
  1.3 s -> 9.4 s, F4 at 2.7 s -> 8.0 s). GDAKI time-to-surface is therefore
  "until the next 10 s tick after the QP enters ERR" (0-10 s, phase-dependent),
  plus the RETRY_EXC time when the error is remote (ref: QP enters ERR ~57 s after
  the fault, host at 59.4 s). **v1's "GDAKI timeout: host never learns" was an
  artifact** of the driver exiting ~5 s after the fault; with 15 s of post-fault
  polling it surfaces in timeout mode too.
- **Device-wait outcome.** timeout mode: both waits return `ncclTimeout`, data
  missing (bounded as designed). proxy blocking: both waits hang (user devComms get
  no abort flag). **GDAKI blocking: the initiator's flush returns success on the
  failed op** (`doca_gpu_dev_verbs_wait` is void and discards the `-EIO` CQE) while
  the receiver hangs -> `init_silent_iters = 1` in every GDAKI blocking F1/F2/F3
  trial and the IB=20 ref, 0 everywhere else. That is the initiator-side silent
  success: one iteration reported done whose data never arrived.
- **Teardown.** `ncclCommAbort` returns in timeout mode and after F4; in proxy
  blocking F1/F2/F3 it **hangs** (the progress thread is stuck on the failed op)
  and the alarm watchdog has to exit. GDAKI teardown returned in all cells.
- **QA item 7 — GDAKI F4 initiator.** Rank 0 first notices the peer's death on the
  management TCP barrier; the drain's first put then ends with device rc **8 =
  ncclTimeout** (the 5 s device cap; v1 labelled this "error"). No NCCL WARN and no
  status/vendor_err appear; the only host-visible sign is the QP-state check
  (`fp_where`=`api`) ~8 s after the kill. Proxy F4 by contrast logs REM_ACCESS 10/0x88
  within 60 ms (the host error is seen during the drain -> init=`error`).
- **F3 vs F4 on the initiator.** F3 (peer QP -> ERR, process alive) exhausts IB
  retries -> RETRY_EXC 12/0x81 (3.6 s at IB=14); F4 (process killed) has its
  MR/QP torn down by the kernel, so the next write is rejected -> REM_ACCESS
  10/0x88 within ~60 ms. On the proxy backend the two are distinguishable; on
  GDAKI both look identical ("QP in ERR").
- **F2 regimes.** A put just past the logical window but inside the page-rounded
  MR (`ncclMemAlloc` rounds to ~2 MiB) raises **no** error (silent loss, v1);
  only a put outside the MR (64 MiB offset, v2) raises REM_ACCESS. The GIN device
  `put` does not bounds-check offsets.
- **GDAKI CQ shape (cross-reference with the CQE-sequence question).** NCCL leaves `cq_collapsed=0`,
  so the GDAKI CQ is a **normal ring** (`DOCA_GPUNETIO_VERBS_CQ_64B`, size = `sq_nwqe` =
  `NCCL_GIN_GDAKI_QP_DEPTH` = 128), indexed per-WQE — not a single-slot collapsed CQ. The root-cause
  CQE sits at its slot, but the device reads only the opcode and the host only the QP state, so
  neither the root cause nor a flush syndrome (5/0xf9) is exposed in a production build (the
  syndrome prints only under `DOCA_GPUNETIO_VERBS_ENABLE_DEBUG`).
- GIN honours `NCCL_IB_TIMEOUT` on both backends (proxy QPs via
  `ncclIbConnectImpl`, GDAKI via `doca_verbs_qp_attr_set_ack_timeout`).

Evidence: v2 per-rank logs/KV in `results/20260923/v2/logs/` (hook lines
`GIN/FAULT: ... fired: moved N/N ... fire_mono_ms=`, proxy WARNs
`NET/IB/GIN: Got completion ... status=12 ... vendor err 129`, GDAKI
`GIN Error detected`, F4 `drain_device_rc=8`); refs in `results/20260923/ref60/`.

## Limitations

* pre-Hopper GPUs here -> GDAKI runs in its **CPU-doorbell fallback** (no `PeerMappingOverride`, no
  gdrdrv); the CQ is still in GPU memory and polled by the GPU (the codepath the per-stack fault
  measurement targets), but doorbell ringing is not GPU-initiated.
* Registered/symmetric memory kept small (256 KiB window) for rain's 256 MiB BAR1.
* Non-blocking comm (the 2.32 docs' prescription for safe abort) was not used:
  symmetric-window registration failed under it in this build
  (`ncclCommEnsureReady`: "communicator used before the previous op returned
  ncclSuccess"). Abort is bounded by an alarm watchdog instead; the proxy-blocking
  abort hang is measured on a blocking comm.
* GDAKI host detection depends on the phase of the 10 s query throttle relative to
  the fault, so its `surface_ms` (8-10 s here) reflects our fixed timeline (fault
  0.7-2.7 s after start), not a property of the fault.
* The lead's IB=20 proxy rows come from the older driver; their `surface_ms` is an
  estimate (see above). Only one GDAKI IB=20 reference trial was run.
* F4 uses a lockstep barrier plus a post-kill drain of puts; without the drain
  the initiator would learn of the death only via the TCP barrier (FIN).
