# nvshmem_ft: 상세 기록

이 문서는 예전 README 본문(v1)을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`../propagation/review_20261006/nvshmem.md`)
- "`nvshmem_finalize` returned on every surviving PE (17-29 ms)"는 앱의 거절 경로가 FT 중단 API를 부를 때만 맞다. 종료 때 barrier 건너뛰기를 빼면 종료가 멈췄다(`V2.md` C절, F2b 5/5, F4 3/3).
- 오류는 FT 상태 조회나 시간 제한 quiet로만 보인다. quiet는 여전히 결과값이 없다. Limitations의 "barrier와 집합 연산은 오류 뒤 돌아오지만 오류를 전하지 않는다"는 소스로만 확인했다.
- 재설정 단계가 모두 검증됐다는 요약은 묶음으로만 확인된 것이다. 하나씩 빼 보니 꼭 필요한 것은 6가지였다(`V2.md` C절).
- `V2.md`의 "fetch 옛 값 버그는 v1부터"는 추론이다. v1 빌드에서는 fetch를 돌리지 않았다.
- `V2.md`의 "sentinel 없이 90/90"은 v2 빌드에서 잰 값이다. F3, F4의 분류, 복구, 거절은 v2.2에서 다시 돌리지 않았다(v1, v2 결과).
- fetch 옛 값의 수는 범위에 따라 둘이다. `V2.md`의 456,125(35회)는 일반 모드 5칸의 합이다. 리뷰와 `../RESULTS.md`의
  510,028(40회)은 진단 모드 5회를 더한 v2.1 전체이고, 그중 3회는 멈춰 값이 없다. 원시 로그로 다시 세면 둘 다 맞다.
- N30(`results/20260925_n30/`)은 rain `mlx5_1`의 펌웨어 명령 슬롯 하나가 샌 상태(09-25 06:45부터)에서 돌았다(07:04–07:31).
  N30 문서에는 이 언급이 없다(`../gin_recovery/TRANSPARENT_S1.md`).

Brings the approach of `../gin_q4/` (device classifies the root-cause CQE, host mailbox, waits
return an error) and `../gin_recovery/` (kernel returns, host prepare / handshake / commit with a
bilateral QP reset, fresh PSNs and a device-state resync, the application replays the data and only
the missing signal delta) to NVSHMEM IBGDA. Same cluster: rank 0 = rain (initiator, Quadro RTX 5000
sm_75, mlx5_1), rank 1 = sunny (target, RTX A4000 sm_86, mlx5_0), ConnectX-6 (VPI, MT28908) RoCE,
`NVSHMEM_IB_TIMEOUT=14`, PeerMappingOverride=1 on both nodes, so NVSHMEM's NIC handler is the GPU
(the GPU rings the doorbell; the send CQ is collapsed and in GPU memory). One RC QP per PE
(`NVSHMEM_IBGDA_NUM_RC_PER_PE=1`); DCIs exist but carry no traffic. The design and the safety
argument are in `DESIGN.md`.

## TL;DR

- **Classification is exact and reaches the host in ≈0.07 ms.** 48/48 single-fault trials (both
  wait modes) and 100/100 rounds of the five-fault runs recorded the true root cause: F1 LOCAL_QP_ERR
  5/0xf5, F2b REM_ACCESS 10/0x88, F3 and F4 RETRY_EXC 12/0x81. The watcher read the record 67 us
  (median; 8-137 us, n=222) after the device captured it. Fault -> host-visible error code in the
  single-fault runs: F1 3.4-4.2 ms (the fault lands between operations; the next put meets it),
  F2b 1.2-2.5 ms after the bad put, F3 3.50-3.68 s and F4 3.61-3.79 s (retry exhaustion at IB
  timeout 14).
- **No silent success, no hang in the waits.** With the flag on, every failed operation was reported
  by both `nvshmem_quiet` + `nvshmemx_ibgda_ft_status` and the bounded quiet. In the same build with
  the flag off, the blocking `nvshmem_quiet` reported success for the failed put in 6/6 fault trials
  (slot 5/0xf9) and teardown hung on both PEs in 8/8.
- **Where the collapsed slot is read decides what is classified.** Read where the stock wait ends
  (the CQE that satisfies it), 24/24 faults looked like the trailing flush 5/0xf9. Read inside the
  spin loop, the root cause was kept whenever the wait was spinning when it arrived: 21/30, and every
  trial of the patterns "post, then wait" (single, burst of 16). It was lost (9/30) when the kernel
  computed for 0.2-2 ms between posting and waiting and the root cause arrived meanwhile. A device
  sentinel thread kept it in 18/18, including those patterns.
- **Transient faults recover with nothing lost or doubled.** F1 (local QP -> ERR) and F3 (peer QP ->
  ERR, peer alive) recovered in every trial of both wait modes: 12 single-fault runs and 20 runs
  with 5 faults each, one of which strikes inside the previous commit and hits the replay. That is
  112 recovery rounds (20 of them a second round for the same operation); every one of the 200
  operations per run was verified bit-exact with an exact signal, and V was always expected - 1
  (d = 1). Forced recoveries after completed operations (d = 0, 6/6) replayed nothing.
- **Recovery takes ≈3 ms of host time after the kernel returns** (median 3.08 ms, 2.69-5.67):
  prepare 0.15-0.5 ms, handshake (incl. the responder's prepare and commit) 1.2-2.9 ms, commit
  1.0-1.5 ms, replay 0.06-0.08 ms, for one RC QP (+ one DCI) per side. Fault -> recovered: F1
  ≈6.7 ms, F3 3.51-3.76 s.
- **Unrecoverable faults decline cleanly and teardown returns.** F2b is declined (class) 1.2-2.5 ms
  after the bad put, F4 (RETRY_EXC with FIN on the OOB socket) 3.6-3.8 s after the kill, the
  CPU-proxy NIC handler is declined (configuration). `nvshmem_finalize` returned on every surviving
  PE (17-29 ms), including with a dead peer; stock NVSHMEM hangs there.
- **No measurable no-fault cost.** put+signal+quiet p50: 4 KiB 12.58 -> 12.70 us (+0.12 us, 1%),
  256 KiB 40.32 -> 40.42 us (+0.25%); the sentinel added nothing measurable. (A first version
  that read the slot and the sticky record with separate loads cost +0.58 us at 4 KiB.)

## What was built

| piece | what |
|---|---|
| `nvshmem_ibgda_ft.diff` | NVSHMEM patch (+≈1340 lines, 8 files), layered on `7bb2e99c` + `../nvshmem/nvshmem_ibgda_fault_inject.diff` + `../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff` (the version committed in b0562a2); gated by `NVSHMEM_IBGDA_FT=1`, default off |
| `DESIGN.md` | contract, classification on a collapsed CQ, preconditions, quiescence model, protocol, reset/resync inventory, replay semantics, safety argument, what the tests changed |
| `nvshmem_ft.cu` | 2-PE driver (from `../nvshmem/nvshmem_fault.cu`): lockstep put+signal with per-iteration verification, OOB protocol, recovery loop, capture-study and latency modes |
| `scripts/` | build, deploy, trial / matrix runners, specs, log -> CSV, tables, diff regeneration + verification |
| `results/b2/` | final build (all tables below); `results/b1/` first build (same host code, older device loop; superseded, kept for the incidents in DESIGN §10); `results/smoke/` first end-to-end runs |

### Device side (`ibgda_device.cuh`, `nvshmem_common_ibgda.h`)

- `ibgda_poll_cq` (used by `nvshmem_quiet`, fence and the WQE-slot wait of every put) reads CQE
  word 15 once per spin iteration; if the opcode is 0xd/0xe it snapshots the 64-byte CQE
  (word 15 equal before and after), classifies (syndrome, vendor_err) with the rdma-core table,
  keeps a sticky first-error record per QP in the 24 formerly unused padding bytes of the QP's
  management variables, publishes a 256-byte record to a host-mapped mailbox (system-scope stores,
  `seq`, then `magic`), and returns -1 at once. Struct sizes are unchanged (the FT pointer takes
  12 of the device state's 44 reserved bytes).
- New device API: `nvshmemx_ibgda_ft_status(pe)` (packed opcode, syndrome, vendor_err and class of the first error on an RC QP
  to `pe`, 0 if none; this is how a kernel learns that `nvshmem_quiet()` failed),
  `nvshmemx_ibgda_ft_quiet_bounded(pe, cycles)` (0 / -1 error / -2 budget expired),
  `nvshmemx_ibgda_ft_sentinel(poll_ns)` (device sentinel, see the capture study).

### Host side (`ibgda.cpp`, host library)

- Mailbox (16 x 256 B, `cudaHostAlloc` mapped) and a watcher thread (default 50 us poll) that logs
  one line per record with the status/vendor_err pair, class, cause and action (wording of
  `harness/common/probe.c classify()`), then DEVX `QUERY_QP`s the QP. Example (F2b, `results/b2`):

  ```
  [nvshmem-ft] PE0 device-classified error CQE seq=1 qpn=0x... qp_type=RC peer=1 wqe=23 path=poll
    fp=10/0x88 syndrome=0x13 class=REM_ACCESS fault=rem_access cause="remote access: invalid rkey or
    out-of-bounds addr" action="refresh rkey / clamp to remote MR bounds, QP-only recover" root_op=0xd ...
  [nvshmem-ft] PE0 host QUERY_QP qpn=0x... ret=0 state=6(ERR) hw_sq_wqebb=25 sw_sq_wqebb=25 query_us=111
  ```
- Exported C API (resolved with `dlopen("nvshmem_transport_ibgda.so.7", RTLD_NOLOAD)` + `dlsym`;
  the plugin's version script now also exports `nvshmemt_ibgda_ft_*`): `ft_query` (first
  unrecovered record, optional wait), `ft_prepare(peer)` (quiescence check from the device's own
  variables, QPs -> ERR, drain until `QUERY_QP.hw_sq_wqebb_counter` = device producer, fresh
  24-bit PSNs), `ft_commit(peer, token)` (2RST, CQ refill 0xff + doorbell record 0 + management
  variables 0, then INIT/RTR/RTS with the stored connect-time peer handle and the exchanged PSNs;
  local DCIs not in RTS reset too), `ft_abort(peer)` / `ft_mark_failed()` (QPs stay in ERR; a new
  transport attribute bit makes the host library skip device barriers and the bootstrap barrier at
  teardown), `ft_sentinel_stop`, `ft_commits`.
- `ibgda_rc_init2rtr` / `ibgda_qp_rtr2rts` take PSN parameters (default 0 = stock values); the
  connect path keeps each RC endpoint's peer handle for the reconnect.
- Fault hook extended to several shots: `NVSHMEM_IBGDA_FAULT_INJECT=<act>:<ms>,<d2>,...` fires
  shot k d_k ms after the recovery commit that followed shot k-1 (-1: inside it, right after RTS,
  so it hits the replay); each shot logs `fire_mono_ms`.

### Driver (`nvshmem_ft.cu`) and application duties

PE0 posts `nvshmem_putmem_signal_nbi` (256 KiB RDMA WRITE + signal ADD 1) and completes it with
`nvshmemx_ibgda_ft_quiet_bounded` (timeout mode) or `nvshmem_quiet` + `nvshmemx_ibgda_ft_status`
(blocking mode); PE1 waits for the signal (bounded spin or `nvshmem_signal_wait_until`) and
verifies all bytes; iterations are lockstep over the OOB socket (the unique-ID TCP socket on eno1,
kept open). On an error the initiator follows DESIGN §5: policy (LOCAL_QP_ERR recover; RETRY_EXC
recover only if the OOB socket shows the peer alive; everything else decline), prepare, REQ,
responder prepare + reads V + commit, ACK{d}, commit, replay the last d operations, DONE. On
decline both sides call `ft_abort`/`ft_mark_failed`, the responder releases its own waiter by
writing a cancel marker into its signal from the host, and both tear down.

## Build, deploy, provenance

```
cd <scratch>/ibgda/nvshmem && git archive 7bb2e99c | tar -x -C <src>   # then, in <src>:
git apply ../nvshmem/nvshmem_ibgda_fault_inject.diff
git apply ../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff
git apply nvshmem_ibgda_ft.diff
cmake -S <src> -B <build> (options as in ../nvshmem/README.md, CUDA 12.8, archs 75;86) && make -j && make install
scripts/build_driver.sh      # nvshmem_ft.cu -> <scratch>/gi/nvshmem_ft/nvft_drv (-Wall -Wextra clean)
scripts/deploy.sh            # ~/gi-bundle/nvshmem_ft/{lib,bin} on rain and sunny, md5 checked
scripts/make_diff.sh         # regenerates the diff and verifies it re-applies to the pristine layers
```

- Scratch tree `gi/nvshmem_ft/` (own source copy and build dir); the other agents' builds
  (`~/gi-bundle/nvshmem`, `~/gi-bundle/nvshmem_nrc`, `gi/nvshmem`, `gi/nrc_nvshmem`) were not
  touched. Binary name `nvft_drv` (reaped by exact name only), port 18317.
- Final build (`results/b2`): `libnvshmem_host.so.3.9.0` `e1490a7d...`,
  `nvshmem_transport_ibgda.so.7.0.0` `ca020e99...`, driver `bf69c73e...` (identical on both nodes;
  each trial's `.meta` records the driver and plugin md5).
- `results/b1` ran the first build: same host code, but the device loop read `op_own` and the
  sticky state with separate loads (overhead below). All b1 outcomes match b2.

## Results (final build, `results/b2`)

Every cluster command ran through `../common/cluster_run.sh`: b2 in 2 holds (6 and 10 min), b1 in
4 (4-15 min; hold B was stopped by me after the sentinel hang, DESIGN §10), smoke in 4 (<2 min).
Each trial left no process on either node (`leftover` 0/0 in every row of `trials.csv`). The b2
library was compiled on rain (niced) during the last minutes of b1's hold D, whose runs are
superseded. Fault times: F1 = hook `fire_mono_ms`; F3 = hook on sunny, moved to rain's clock
with the OOB clock offset (min RTT of 30 pings, ≈0.1 ms); F2b = after the rkeys were corrupted,
before the put kernel; F4 = sunny's `CLOCK_MONOTONIC` right before the SIGKILL, same offset. Device
detection = the record's `%globaltimer` on rain's clock (driver calibration, +-3 us).

### Classification (`classify/`, no recovery: every fault is declined and both PEs tear down)

| fault | wait | n | recorded class | status/vendor_err | read by | fault -> device (ms) | device -> mailbox (us) | teardown r0 / r1 (finalize ms) |
|---|---|--:|---|---|---|---|---|---|
| none | timeout / blocking | 3 / 3 | - | - | - | - | - | returned (20 / 26) |
| F1 local QP -> ERR | timeout | 3 | LOCAL_QP_ERR 3/3 | 5/0xf5 | bounded quiet | 3.50 [3.46-3.60] | 65 [59-99] | returned (19 / 25) |
| F1 | blocking | 3 | LOCAL_QP_ERR 3/3 | 5/0xf5 | `nvshmem_quiet` | 3.60 [3.33-4.08] | 60 [21-76] | returned (19 / 25) |
| F2b invalid rkey | timeout | 3 | REM_ACCESS 3/3 | 10/0x88 | bounded quiet | 1.27 [1.22-2.24] | 14 [11-20] | returned (19 / 25) |
| F2b | blocking | 3 | REM_ACCESS 3/3 | 10/0x88 | `nvshmem_quiet` | 1.22 [1.21-1.23] | 33 [24-48] | returned (19 / 25) |
| F3 peer QP -> ERR | timeout | 3 | RETRY_EXC 3/3 | 12/0x81 | bounded quiet | 3615 [3579-3678] | 74 [27-116] | returned (18 / 26) |
| F3 | blocking | 3 | RETRY_EXC 3/3 | 12/0x81 | `nvshmem_quiet` | 3603 [3602-3623] | 81 [67-105] | returned (18 / 26) |
| F4 peer SIGKILL | timeout | 3 | RETRY_EXC 3/3 | 12/0x81 | bounded quiet | 3729 [3613-3794] | 91 [28-102] | returned (18) / killed |
| F4 | blocking | 3 | RETRY_EXC 3/3 | 12/0x81 | `nvshmem_quiet` | 3783 [3731-3792] | 116 [106-123] | returned (18) / killed |

Medians [min-max]. The same 24 classes were recorded in the 24 fault trials of `recover/`.
F2b: the put kernel started 8-28 us after the fault stamp and the REM_ACCESS CQE arrived
1.2 ms after the WQEs were posted (2.2-2.5 ms in 2 trials); in `results/b1` that gap was 4.4-5.6 ms
in one batch, for reasons not identified (it lies before detection). F4: the kill closes the
peer's socket at once, but puts in the first ≈1 ms after the FIN still completed; the first put the
dead QP no longer ACKed ended in RETRY_EXC. The records also carry `wqe_counter` (the failing
WQE: 117 = the RDMA WRITE of the put+signal pair; 23 for F2b) and the snapshot needed one read
in every trial (`snap_tries=1`).

### Root-cause capture on the collapsed CQ (`capture_blocking/`, `nvshmem_quiet` path)

Recorded class per trial (root cause / trailing flush 5/0xf9). "Stock position" classifies the
CQE that ends the wait (`NVSHMEM_IBGDA_FT_CAPTURE=exit`, diagnostic); "in-loop" is the default;
"sentinel" adds `nvshmemx_ibgda_ft_sentinel(200 ns)` in its own kernel (the "read by" column says
which of the two recorded first).

| fault | posting pattern | stock position | in-loop | in-loop + sentinel |
|---|---|---|---|---|
| F1 | put+signal, then wait | 0/3 (all 5/0xf9) | **3/3** | - |
| F1 | 16 x put+signal, then wait | 0/3 | **3/3** | - |
| F1 | put+signal, 200 us compute, wait | 0/3 | 0/3 | **3/3** (sentinel) |
| F1 | put+signal, 2 ms compute, wait | - | 0/3 | **3/3** (sentinel) |
| F2b | put+signal, then wait | 0/3 | **3/3** | **3/3** (in-loop) |
| F2b | 16 x put+signal, then wait | 0/3 | **3/3** | - |
| F2b | put+signal, 200 us compute, wait | 0/3 | **3/3** | **3/3** (in-loop) |
| F2b | put+signal, 2 ms compute, wait | 0/3 | 0/3 | **3/3** (sentinel) |
| F2b | 16 x put+signal, 2 ms compute, wait | - | - | **3/3** (sentinel) |
| F3 | 16 x put+signal, then wait | 0/3 | **3/3** | - |
| F3 | put+signal, 2 ms compute, wait | - | **3/3** | - |
| **total** | | **0/24** | **21/30** | **18/18** |

- The stock position always sees the flush of the last WQE, as predicted by the CQE-sequence measurement (`../cqe_seq/`) and seen in GDAKI
  (`../gin_q4/`): with put+signal the wait is for the signal's WQE, whose flush follows the root
  cause.
- In-loop keeps the root cause when some thread is spinning on the CQ while it arrives: always
  for RETRY_EXC (3.6 s after posting); for REM_ACCESS unless the compute outlasts its arrival
  (1.14-1.28 ms after posting, measured by the device record); never for F1 with compute: the head
  flush 5/0xf5 of WQEs posted to a QP already in ERR arrived 12-62 us after posting, and the
  trailing 5/0xf9 had overwritten it before the 200 us compute ended.
- The same study in timeout mode (`results/b1/capture/`, the bounded quiet, which always reads
  in-loop, so its `cexit` cells are in-loop too) gave the same in-loop and sentinel outcomes.

### Recovery (`recover/`, `multi/`, `d0/`)

| fault | wait | runs | faults per run | recovery rounds | ops verified bit-exact (r1) | final signal exact | declined | teardown r0 / r1 |
|---|---|--:|---|---|---|---|---|---|
| none | timeout / blocking | 3 / 3 | 0 | 0 | 200/200 each | 6/6 | - | returned |
| F1 | timeout / blocking | 3 / 3 | 1 | 1 each (d = 1) | 200/200 each | 6/6 | - | returned |
| F3 | timeout / blocking | 3 / 3 | 1 | 1 each (d = 1) | 200/200 each | 6/6 | - | returned |
| F1 x5 | timeout / blocking | 5 / 5 | 5 | 5 each: 4 recovered + 1 replay hit by the next shot | 200/200 each | 10/10 | - | returned |
| F3 x5 | timeout / blocking | 5 / 5 | 5 | 5 each: 4 + 1 | 200/200 each | 10/10 | - | returned |
| forced (d = 0) | timeout / blocking | 3 / 3 | 0 | 1 each (d = 0, nothing replayed) | 200/200 each | 6/6 | - | returned |
| F2b | timeout / blocking | 3 / 3 | 1 | - | 4/4 before the fault | - | class not recoverable (REM_ACCESS) | returned / returned |
| F4 | timeout / blocking | 3 / 3 | 1 | - | 19-21 before the kill | - | RETRY_EXC with the peer dead (FIN) | returned / killed |
| F1, CPU-proxy handler | timeout | 2 | 1 | - | 51 before the fault | - | no error CQE at all: the bounded wait expired (the handler's doorbell-record bug, `../nvshmem_rootcause/`) | returned / returned |
| F1, CPU-proxy + SQ-DBR fix | timeout | 2 | 1 | - | 51 | - | LOCAL_QP_ERR classified, `prepare` declines: recovery needs the GPU handler | returned / returned |

In x5 runs shot 1 fires 800 ms after connect, shots 2, 3 and 5 20 ms after the previous
recovery's commit, shot 4 inside it (after RTS), so it hits the replay: that operation needs a
second round, which reads V again (still expected - 1) and replays again. In all 118 rounds
V + d = expected held (112 with d = 1, 6 forced with d = 0).

Time per round (ms, median [min-max]; kernel return = the host saw the failed kernel finish):

| fault | wait | rounds | fault -> device | kernel return -> commit done | prepare / handshake / commit | commit -> replay done | **kernel return -> recovered** | **fault -> recovered** |
|---|---|--:|---|---|---|---|---|---|
| F1 | timeout | 3 | 3.6 [3.5-3.9] | 2.91 | 0.17 / 1.33 / 1.36 | 0.06 | **2.98** [2.92-2.98] | **6.6** [6.5-6.8] |
| F1 | blocking | 3 | 3.8 [3.7-4.2] | 2.91 | 0.17 / 1.26 / 1.38 | 0.07 | **2.98** [2.92-3.00] | **6.8** [6.7-7.1] |
| F3 | timeout | 3 | 3519 [3514-3528] | 3.35 | 0.25 / 2.00 / 0.99 | 0.08 | **3.44** [3.04-3.73] | **3523** [3517-3531] |
| F3 | blocking | 3 | 3518 [3505-3529] | 3.23 | 0.24 / 1.92 / 0.98 | 0.08 | **3.31** [3.30-3.35] | **3521** [3508-3533] |
| F1 x5 | timeout | 25 | 4.0 [0.6-8.9] | 2.76 | 0.15 / 1.18 / 1.32 | 0.06 | **2.78** [2.69-3.12] | **6.7** [3.3-11.9] |
| F1 x5 | blocking | 25 | 3.9 [0.6-7.3] | 2.75 | 0.15 / 1.18 / 1.31 | 0.06 | **2.79** [2.71-3.09] | **6.7** [3.4-9.9] |
| F3 x5 | timeout | 25 | 3734 [3538-3754] | 5.03 | 0.54 / 2.90 / 1.46 | 0.07 | **4.98** [3.00-5.67] | **3739** [3541-3760] |
| F3 x5 | blocking | 25 | 3734 [3622-3755] | 5.00 | 0.49 / 2.86 / 1.49 | 0.07 | **4.97** [4.47-5.34] | **3739** [3627-3760] |
| forced d = 0 | both | 6 | - | 2.58-2.68 | 0.43-0.45 / 1.34 / 0.77-0.80 | - | 2.6 | - |

- "Kernel return -> recovered" counts rounds whose replay succeeded (92 of the 112 fault rounds;
  the other 20 continue as the next round). Fault -> device for F1 is mostly the wait for the next
  put (the 0.6 ms minima are the in-commit shots hitting the replay).
- Prepare = read the device indices (D2H copy on the library's stream) + `QUERY_QP` + `2ERR` when
  the QP is not already in ERR + drain (0.06-0.07 ms in every cell). The initiator's QP was already
  in ERR in every fault round (QUERY_QP after each record: ERR in 222/222), so its prepare took
  0.08-0.17 ms before the drain; a forced recovery on a healthy QP took 0.37 ms. Commit = 2RST
  0.2-0.3 ms + device resync 0.02-0.04 ms + INIT/RTR/RTS 0.5-1.0 ms (+ a DCI reset when the hook had
  moved the DCI to ERR). The handshake includes the responder's prepare, signal read and commit.
- In the x5 F3 runs these steps were slower on both sides (initiator prepare 0.43 vs 0.17 ms;
  responder prepare 0.45 vs 0.27 ms and commit 2.31 vs 1.53 ms, the same QPs being reset); the cause
  was not isolated.

### Stock behaviour in the same build (`flagoff/`, `NVSHMEM_IBGDA_FT` unset)

| fault | wait | n | initiator's wait on the failed put | target | teardown |
|---|---|--:|---|---|---|
| F1 / F2b / F3 | blocking (`nvshmem_quiet`) | 2 / 2 / 2 | **reported success** (slot 5/0xf9) in 6/6 | never got the data (host bound 15 s) | hung on both PEs (watchdog), 6/6 |
| F3 | timeout (bounded quiet) | 2 | error at exit, no class, no record | same | hung, 2/2 |

The flag-off runs are what NVSHMEM does today on this path (`../gpu_doorbell/`); the driver needed
its lockstep acknowledgement to notice the silent success at all.

### No-fault overhead (`lat/`)

5 x 2000 (put+signal+`nvshmem_quiet`) per run, GPU-timed with `%globaltimer`; 6 interleaved runs
per cell (60k samples); per-run median of the p50 / p99 of the 5 reps:

| bytes | classifier off | on | on + sentinel |
|---|---|---|---|
| 4096 p50 (us) | 12.58 (one run 13.98) | 12.70 | 12.61 |
| 4096 p99 (us) | 13.95 [13.86-14.37] | 13.90 [13.89-13.92] | 13.76 [13.66-13.79] |
| 262144 p50 (us) | 40.32 [40.16-40.32] | 40.42 | 40.42 |
| 262144 p99 (us) | 40.99 | 40.99 | 40.99 |

The timer resolution is ≈32 ns, so identical values across runs are expected. The build `b1`
(separate loads of `op_own` and the sticky record in the spin loop, plus a sticky check on entry)
measured 12.48 -> 13.06 us at 4 KiB and 40.38 -> 40.90 us at 256 KiB; the final loop reads CQE word
15 once per iteration. The watcher thread sleeps 50 us between mailbox scans (no measurable CPU
cost was looked for; it is one mostly sleeping thread per PE).

## Measured vs inferred

- **Measured:** every table above (per-trial logs, CSVs); the classes and raw CQE bytes read by
  the device; host `QUERY_QP` states after each record (ERR in every fault); data verification of
  every operation on the target; exact signal values; step costs; the teardown times; the latency
  distributions; that after `2RST` the replay's CQE carries `wqe_counter` 1 at `ready_head` 2 (the NIC
  restarts at 0); md5 provenance.
- **From source, consistent with the measurements:** why the stock wait ends on the trailing flush
  (it waits for the last WQE); why each resync item is needed (DESIGN §6.3); that the device
  barrier is what hung `nvshmem_finalize` (it is the only step that needs the peer's atomics; with it
  skipped finalize returned, and with a dead peer the remaining 22.9 s were the TCP bootstrap
  barrier's `connect()` retries, visible in the log).
- **Inferred, not tested:** behaviour with several RC QPs per peer, several NICs, more than two PEs,
  or several operations in flight during a recovery (the replay rule of DESIGN §7 covers
  `burst` > 1, but recovery ran with one operation in flight); symmetric initiation; a peer host
  that dies without FIN (covered only by the 5 s handshake deadline); posting far past the ring
  after an error (the slot wait no longer throttles a failed QP); DC (DCI) traffic.

## Limitations

- GPU NIC handler only; the CPU-proxy handlers are declined (and, unpatched, deliver no error CQE).
- **The in-loop classifier needs a thread spinning on the CQ when the root cause arrives.** Kernels
  that post, compute and only then wait need the sentinel, which costs one resident thread, must be
  started after every kernel of the application has been launched once, forbids
  `cudaDeviceSynchronize` while it runs, and must be stopped before teardown (both hazards
  happened, DESIGN §10).
- **`nvshmem_quiet` still returns `void`.** Kernels must ask `nvshmemx_ibgda_ft_status(pe)`;
  NVSHMEM's own internal waits (barriers, collectives) now return on a failed QP but do not
  propagate the error, so an application must not rely on a collective completing after a fault.
- **Quiescence is a contract** (kernels stopped, peer posts nothing until committed); the library
  checks only the device indices. One initiator per QP pair; lockstep operations.
- **LOCAL_QP_ERR is treated as transient**; a persistent local fault is bounded by 6 rounds.
- The target never sees an error by itself (it posts nothing); it learns from the OOB socket.
- F3 and F4 have the same error code; they are told apart only by the OOB socket (FIN), as in the
  CPU harness.
- One node pair, one firmware (20.43.4100), RoCE v2, IB timeout 14; 3 trials per single-fault cell,
  5 per multi-fault cell; the capture study has 3 trials per cell.

## Files

| path | what |
|---|---|
| `DESIGN.md` | design and safety argument |
| `nvshmem_ibgda_ft.diff` | NVSHMEM patch (header: base, layering, env, files) |
| `nvshmem_ft.cu` | driver |
| `scripts/build_driver.sh`, `deploy.sh`, `make_diff.sh`, `env_ft.sh` | build / deploy / diff / environment |
| `scripts/run_trial.sh`, `run_matrix.sh`, `batch_e1.sh`, `batch_e2.sh`, `specs/*.txt` | one trial / one spec / one cluster hold (the b1 holds `batch_a.sh`..`batch_d.sh` and the first `smoke.sh` were removed on 2026-10-06; the timeout-mode capture study of b1 is `run_matrix.sh specs/capture.txt`) |
| `scripts/rows.py`, `summarize.py` | logs -> `trials*.csv` + `events*.csv` -> tables |
| `results/b2/` | final build: per-trial `.meta` and gzipped `.pe0.log`/`.pe1.log`, `matrix.out`, CSVs |
| `results/b1/` | first build, incl. `diag/capture_sentinel_hang` (driver bug, DESIGN §10) |
| `results/smoke/` | first end-to-end runs (s1: FT API resolved too early; s2-s4: F4 and teardown fixes) |

## Reproduce

```
CR=../common/cluster_run.sh
$CR -t nvft-E1 -- timeout 1750 bash scripts/batch_e1.sh     # classify, recover, d0, config, lat
$CR -t nvft-E2 -- timeout 1750 bash scripts/batch_e2.sh     # multi, capture_blocking, flagoff
R=results/b2
python3 scripts/rows.py $R/classify $R/recover $R/d0 $R/config $R/multi $R/capture_blocking $R/flagoff \
        --trials $R/trials.csv --events $R/events.csv
python3 scripts/summarize.py $R/trials.csv $R/events.csv $R/lat > $R/summary.md
```
