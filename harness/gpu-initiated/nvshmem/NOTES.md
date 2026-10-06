# nvshmem: 상세 기록

이 문서는 예전 README 본문을 그대로 옮긴 상세 기록이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정** (`../propagation/review_20261006/nvshmem.md`)
- "364/364 device reads"는 363회다(matrix 336 + f2b 15 + ref 12, 모두 0x0). "51-trial matrix"의 `matrix.csv`는 F2b를 포함해 54행이다.
- `results/20260923/ab/`의 F1, F3(tcc1) 칸은 장애를 시험하지 못했다. 감시 스레드가 락을 잡고 자는 동안 실패한 put이 울리지 않았고, F1의 2ERR은 감시가 끝난 뒤 실행됐다. 감시 없이 돈 matrix와 F2b 칸은 영향이 없다.
- "F3에서 QP가 16 s 동안 RTS"와 "watch thread racing init"은 틀렸다. 감시 스레드가 CPU 프록시를 막은 것이다. 실제로 F3의 QP는 put 뒤 약 3.6 s에 ERR로 간다(`../nvshmem_rootcause/`).
- "collapsed CQ가 원인"은 기각됐다(`../gin_q4/`). 실제 원인은 CPU 프록시가 doorbell record의 엉뚱한 칸에 쓰는 버그다. "QUERY_QP does not report ERR", "puts never retire", "infinite RNR"도 틀렸다.
- cc=0 "init hangs"는 락을 잡은 감시 스레드와 함께 돌아 믿을 수 없다. 감시 없이 다시 재 보니 멈춤은 맞고, 원인은 GPU가 CQ 첫 칸만 읽기 때문이다(`../nvshmem_ft/V2.md` A1).
- "finalize tries to quiesce the broken QP"는 틀렸다. 멈춤은 종료 과정(heap 해제와 finalize)의 GPU barrier에서 온다(`../nvshmem_ft/DESIGN.md` 9절).
- 시간 제한 대기와 DeepEP식 대기의 1.46 / 3.85 / 5.75–5.79 s는 대기에 준 예산이다. 감지 시간이 아니다.
- 장애 뒤 종료: 리뷰는 "12/12 + F2b 3/3"으로 적었으나 `matrix.csv`를 다시 세면 장애 시행 30회(F1, F3, F4 각 9회와
  F2b 3회)가 모두 exit 7이다. 블로킹 9회는 대기에서, 나머지 21회는 종료 과정에서 멈췄다. 참고 측정 2회도 같다.
- "1 F3 reference at the default IB timeout"은 2회다(`matrix_ref.csv`, 대기 예산 15 s와 40 s). 363회 읽기에 둘 다 들어 있다.

GPU-initiated RDMA fault characterization for the **NVSHMEM IBGDA** transport, on the rain (client,
mlx5_1, Quadro RTX 5000 / sm_75) + sunny (server, mlx5_0, RTX A4000 / sm_86) RoCE cluster. Answers
the per-stack fault measurement (which layer notices a fault, whether the status/vendor_err pair is
visible, whether the device wait hangs / times out / returns success, whether data is correct, time
to surface, whether teardown returns) and the NVSHMEM CQ-slot read (read the collapsed CQ slot from
device code: opcode, syndrome, vendor_err_synd, wqe_counter, qpn) from `../DESIGN.md`.

## TL;DR

- IBGDA's device completion path (`ibgda_poll_cq` in
  `non_abi/device/pt-to-pt/ibgda_device.cuh`) checks only `opcode ==
  MLX5_CQE_REQ_ERR`, then `ibgda_quiet` does `assert(status == 0)`. **The default
  release build compiles with `-DNDEBUG` (confirmed in the generated
  `flags.make` for both the host transport and the device library, sm_75+sm_86),
  so that assert is a no-op.** By the code, an error CQE would therefore be
  ignored and the blocking quiet would return "success". In practice no error CQE
  ever reached the CQ here (see Root cause), so every wait on a failed put simply
  never completes: the blocking quiet hung for every fault, and the bounded and
  DeepEP-style waits spun to their budget. (2026-09-24: the missing CQEs are an
  NVSHMEM bug in the CPU-proxy handler, which writes the send producer index into
  the wrong doorbell-record word; see `../nvshmem_rootcause/`. With the GPU handler
  the CQEs arrive, and the blocking quiet then did return "success" on a failed put,
  see `../gpu_doorbell/`.)
- On this hardware the NIC handler auto-selects **CPU-with-host-memory** (no
  `PeerMappingOverride`, no gdrdrv, driver 12080 predates the CUDA DMA-BUF
  path): the GPU writes WQEs and a CPU proxy rings the doorbell. NIC buffers are
  on GPU memory; the CQ is in GPU memory and collapsed (`cc=1`: 1024 physical
  entries but the NIC only ever writes slot 0, confirmed by a full-buffer scan).
- No fault produces a decoded error code anywhere in the stack, and no QP is
  ever reset. Teardown (`nvshmem_finalize`) hangs after a QP error.

## Build

From-source NVSHMEM at commit `7bb2e99c`, CUDA 12.8, built on rain, deployed to
`~/gi-bundle/nvshmem/` on both nodes (device code is fatbin sm_75 + sm_86;
`libnvshmem_host.so` and the transport / bootstrap plugins are copied over).

```
cmake -S src -B build -DCMAKE_BUILD_TYPE=release \
  -DNVSHMEM_IBGDA_SUPPORT=ON \
  -DNVSHMEM_MPI_SUPPORT=OFF -DNVSHMEM_SHMEM_SUPPORT=OFF -DNVSHMEM_PMIX_SUPPORT=OFF \
  -DNVSHMEM_UCX_SUPPORT=OFF -DNVSHMEM_BUILD_TESTS=OFF -DNVSHMEM_BUILD_EXAMPLES=OFF \
  -DNVSHMEM_BUILD_PYTHON_LIB=OFF -DNVSHMEM_BUILD_PYTHON_DEVICE_LIB=OFF \
  -DNVSHMEM_BUILD_BITCODE_LIBRARY=OFF -DNVSHMEM_BUILD_LTOIR_LIBRARY=OFF \
  -DNVSHMEM_BUILD_HYDRA_LAUNCHER=OFF -DNVSHMEM_BUILD_TXZ_PACKAGE=OFF \
  -DCMAKE_CUDA_ARCHITECTURES="75;86" -DNVSHMEM_DEVICELIB_CUDA_ARCHITECTURES=INHERIT \
  -DNVSHMEM_PREFIX=<prefix> -DCMAKE_INSTALL_PREFIX=<prefix>
```

- Bootstrap: unique-ID over our own TCP socket on the management NIC (eno1); no
  MPI/PMI. The driver uses `nvshmemx_get_uniqueid` / `nvshmemx_set_attr_uniqueid_args`
  / `nvshmemx_init_attr(NVSHMEMX_INIT_WITH_UNIQUEID, ...)`.
- **Device asserts are compiled out** in this default release config (`-O3
  -DNDEBUG`), so `ibgda_quiet`'s `assert(likely(status == 0))` is a no-op — the
  central fact of the per-stack fault measurement.

`build_driver.sh` compiles the driver (`-rdc=true`, links `libnvshmem_host` +
`libnvshmem_device`), warning-free under `-Wall -Wextra`.

### Bringing IBGDA up on a 256 MiB BAR1 (env in `env_common.sh`)

Getting a 2-PE IBGDA put working required working around this box, all via env
(no source change to the transport data path):

- `NVSHMEM_REMOTE_TRANSPORT=none` — the default host proxy transport (ibrc) is
  otherwise also initialized and registers the symmetric heap with plain
  `ibv_reg_mr`, which fails here; skipping it leaves IBGDA (enabled separately by
  `NVSHMEM_IB_ENABLE_IBGDA=1`) as the only IB transport, and it registers the
  heap with `ibv_reg_dmabuf_mr`.
- The **whole heap is registered with the NIC in one shot** and BAR1 is only
  256 MiB. Stock NVSHMEM builds a ≈1.5 GiB heap (`heapextra` ≈ 1.28 GiB from 256
  teams' psync + a 64 MiB coalescing buffer, rounded to a 512 MiB granularity
  when VMM is off). We shrink it well under 64 MiB: `NVSHMEM_MAX_TEAMS=4`,
  `NVSHMEM_G_BUF_SIZE=262144`, `NVSHMEM_G_COALESCING_BUF_SIZE=4194304`,
  `NVSHMEM_SYMMETRIC_SIZE=16M`, `NVSHMEM_DISABLE_CUDA_VMM=1` (a VMM heap VA is
  reported non-device by `cudaPointerGetAttributes` on this driver, forcing the
  failing `ibv_reg_mr` path; cudaMalloc is reported as device and takes the
  working dmabuf path), `NVSHMEM_CUMEM_GRANULARITY=2097152`.
- HCA/GID: `NVSHMEM_HCA_LIST` + `NVSHMEM_ENABLE_NIC_PE_MAPPING=1` pin rain→mlx5_1,
  sunny→mlx5_0; RoCE v2 IPv4 GID index is auto-detected per node (rain 4, sunny 3).
- Confirmed from `NVSHMEM_DEBUG=INFO`: "Successfully initialized the transport:
  IBGDA. It will be used for device-side APIs over IB", "NIC buffer will be on
  GPU memory", "NIC handler will be CPU with host memory backend". No ibrc.

## Patch (fault injection)

`nvshmem_ibgda_fault_inject.diff` — a minimal, default-OFF test + diagnostic
hook in `src/modules/transport/ibgda/ibgda.cpp` (≈269 added lines, applies with
`git apply --check` clean on commit `7bb2e99c`). Both features are gated by env
vars; unset, the build is behaviourally identical to stock.

- `NVSHMEM_IBGDA_FAULT_INJECT=local_err:<ms>` / `peer_err:<ms>` / `qp2err:<ms>`
  (aliases): a detached host thread, armed at the end of `connect_endpoints`,
  sleeps `<ms>` then walks this PE's selected devices' RC and DCI endpoints and
  moves each DEVX QP to the ERR state (`MLX5_CMD_OP_2ERR_QP`, layout declared
  locally since it is not in the vendored `mlx5_ifc.h` subset). A PE can only
  modify its own QPs, so **F1 (local_err)** sets the var on rain and **F3
  (peer_err)** sets it on sunny.
- `NVSHMEM_IBGDA_FAULT_WATCH=<period_ms>` (diagnostic): a host thread that every
  period issues `QUERY_QP` (qpc.state + SQ wqebb counters) on each RC/DCI QP and
  `QUERY_CQ` (cqc producer/consumer/status) on its send CQ, and dumps the 64-byte
  collapsed CQ slot — used to locate where a requester error completion goes.
- **F2a (`oob_within_mr`)** and **F2b (invalid rkey)** need no library change:
  the driver's `--oob` writes one window past the destination buffer (still
  inside the registered heap MR), and `--corrupt-rkey <it>` overwrites all 64
  `constmem.rkeys` entries in the `__constant__` device state via
  `cudaMemcpyToSymbol` so the next put carries an invalid rkey.
- **F4 (proc_kill)** needs no library change: the runner SIGKILLs the peer by
  exact binary name mid-run.

## Driver (`nvshmem_fault.cu`)

2-PE driver. PE0 (rain, initiator) puts M bytes (default 256 KiB) of an
`(iteration, byte-index)` pattern to PE1 (sunny) with
`nvshmem_putmem_signal_nbi` (RC QP, RDMA write + signal atomic), then completes
the operation with one of four wait modes; PE1 waits for the signal and verifies
every byte. Every wait is bounded (device `clock64` budget, or a host `alarm`
watchdog for the library's unbounded paths). Host `CLOCK_MONOTONIC` per iteration.

- `timeout` — PE0 runs its **own** bounded CQ poll (spins on the collapsed
  slot's `wqe_counter` AND classifies `MLX5_CQE_REQ_ERR` itself); PE1 bounded-
  spins on the signal word. Neither side calls the library's unbounded
  `ibgda_quiet`.
- `blocking` — PE0 calls the library `nvshmem_quiet()` (its `ibgda_poll_cq` has
  the on-error assert compiled out under NDEBUG). Bounded only by a host watchdog.
- `deepep_poll` — PE0 spins on `wqe_counter` **only**, never inspecting `op_own`
  for the success decision (the DeepEP-legacy behaviour), to show whether an
  error CQE is taken as success.
- `snapshot` (the CQ-slot read, per lead request) — after posting `--burst N` puts, PE0
  continuously records every change of the collapsed CQ slot into a host-mapped
  ring `(t_cycles, opcode, syndrome, vendor_err, wqe_counter)`, so we can see
  whether the root-cause CQE is ever observable and for how long before flush
  CQEs overwrite slot 0.

**CQ-slot read**: when the wait ends (success or bounded-spin expiry) PE0's device code
reads the collapsed CQ slot of the RC QP it used, through
`nvshmemi_ibgda_device_state_d.globalmem.rcs[peer].tx_wq.cq->cqe`, as raw bytes
(op_own byte 63, syndrome byte 55, vendor_err byte 54, wqe_counter bytes 60-61
BE) plus qpn, into host-mapped memory; the host logs them. Syndrome→ibv_wc_status
uses the rdma-core `providers/mlx5/cq.c` table (verified from a depth-1 clone).

## Results

Runs go through `../common/cluster_run.sh` (cluster lock + idle-link wait).
`NVSHMEM_IB_TIMEOUT=14` for trials; one F3 reference at the default (20).
Per-trial CSV rows in `results/<date>/matrix.csv`; aggregate in
`results/<date>/summary.md` (regenerate with `summarize.py`).

51-trial matrix (`matrix.csv`) + 1 F3 reference at the default IB timeout
(`matrix_ref.csv`) + snapshot/burst captures (`snap/`). `backend =
CPU_with_host_memory` and `stack = nvshmem-ibgda` for every row.

| fault | wait_mode | n | init_outcome | target_outcome | data_check | silent_success | error CQE seen | teardown | time to surface |
|---|---|--:|---|---|---|--:|---|---|---|
| none (baseline) | timeout | 5 | ok | ok | ok | 0/5 | none (op 0x0) | clean | n/a |
| none | blocking | 5 | ok | ok | ok | 0/5 | none | clean | n/a |
| none | deepep_poll | 5 | ok | ok | ok | 0/5 | none | clean | n/a |
| F1 local_err | timeout | 3 | hang_killed | timeout | missing | 0/3 | **none** | **hang** | ≈1.46 s (device budget) |
| F1 | blocking | 3 | hang_killed | ok\* | ok\* | 0/3 | none | **hang** | 30 s (watchdog only) |
| F1 | deepep_poll | 3 | hang_killed | timeout | missing | 0/3 | none | hang | ≈1.46 s |
| F2a oob_within_mr | timeout | 3 | **ok** | ok | **mismatch** | **3/3** | none (op 0x0) | clean | never (silent) |
| F2a | blocking | 3 | **ok** | ok | **mismatch** | **3/3** | none | clean | never (silent) |
| F2a | deepep_poll | 3 | **ok** | ok | **mismatch** | **3/3** | none | clean | never (silent) |
| F2b invalid_rkey | timeout | 3 | hang_killed | timeout | missing | 0/3 | **none** (op 0x0) | **hang** | ≈3.85 s (device budget) |
| F3 peer_err | timeout | 3 | hang_killed | timeout | missing | 0/3 | **none** | **hang** | ≈5.75 s (device budget) |
| F3 | blocking | 3 | hang_killed | ok\* | ok\* | 0/3 | none | **hang** | 30 s (watchdog only) |
| F3 | deepep_poll | 3 | hang_killed | timeout | missing | 0/3 | none | hang | ≈5.79 s |
| F3 (reference, IB_TIMEOUT=20) | timeout | 1 | hang_killed | — | missing | 0/1 | **none even at 38.1 s** | hang | > 38 s |
| F4 proc_kill | timeout | 3 | hang_killed | killed | ok\* | 0/3 | **none** | **hang** | ≈5.79 s (device budget) |
| F4 | blocking | 3 | hang_killed | killed | ok\* | 0/3 | none | **hang** | 30 s (watchdog only) |
| F4 | deepep_poll | 3 | hang_killed | killed | ok\* | 0/3 | none | hang | ≈5.79 s |

\* blocking mode runs the loop to completion reporting each `nvshmem_quiet()` as
success; the failing iteration's quiet then hangs and the per-iteration watchdog
kills the process, so `data_check`/`target_outcome` reflect the last *pre-fault*
iteration, not recovery. For F4 the data arrived before the peer was killed.

**CQ-slot read (collapsed-slot contents).** Read after every wait, plus 45 continuous
snapshot transitions across 15 s windows (burst 1 and 16): the slot's opcode was
`0x0` (MLX5_CQE_REQ, a normal completion) in **364/364** device reads and
**45/45** snapshot samples. An error CQE (`opcode 0xd`, MLX5_CQE_REQ_ERR) was
**never** observed, so `syndrome`/`vendor_err_synd` never carried a real
error code (the bytes read on a normal CQE are the completion's timestamp
field). `wqe_counter` freezes at the last successful WQE (e.g. 24) once the fault
hits; `ready_head` keeps advancing as the kernel posts, so the gap
`ready_head - 2*wqe_counter` is the only device-visible sign of trouble.

## Root cause (why no error CQE is ever visible)

> **Update 2026-09-24: root cause found; parts of this section are superseded.**
> See `../nvshmem_rootcause/` and `../gpu_doorbell/`.
> - **Cause.** With the CPU-proxy NIC handler (our only option without
>   PeerMappingOverride), `ibgda_rc_progress` / `ibgda_dci_progress` write the send
>   producer index into word 0 of the QP doorbell record (the *receive* counter,
>   `MLX5_RCV_DBR`) instead of word 1 (`MLX5_SND_DBR`). Normal traffic works because the
>   UAR doorbell carries the index; at the ERR transition the NIC takes the producer from
>   the record (0), sees an empty send queue and writes no completion. Fixing only that
>   word (default-off knob in `../nvshmem_rootcause/nvshmem_nrc_proxy_sq_dbr.diff`) brings
>   REM_ACCESS, RETRY_EXC and WR_FLUSH CQEs back; so does the GPU handler, which writes
>   word 1 (`../gpu_doorbell/`).
> - **"F3 leaves the requester QP in RTS" is wrong.** It was produced by the
>   `NVSHMEM_IBGDA_FAULT_WATCH` thread, which held `rc_endpoint_lock` while sleeping; the
>   CPU proxy needs the same lock, so the failing put was never rung during the watch.
>   Without that artifact the QP goes to ERR ≈3.6 s after the put, as with verbs. The
>   "watch raced init" explanation below is wrong for the same reason.
> - **The `ab/` F1 and F3 cells (tcc1) never exercised the fault** (the put was not rung,
>   and F1's 2ERR ran after the 16 s watch), and the `cc=0` "init hangs" result ran with
>   the lock-holding watch, so it is unreliable. The collapsed-CQ hypothesis was rejected
>   separately in `../gin_q4/`.
> - Still valid: the full-buffer scan (no 0xd/0xe anywhere), F2b's QP in ERR without a
>   CQE, the release build compiling the assert out, and the teardown hangs.

Each statement below is tagged **[measured]** or **[inferred]**. Two round-2 QA
gaps (full-buffer scan; QUERY_QP parse) were closed and corrected earlier text.

**[measured] No error CQE is written anywhere in the send CQ — full buffer, not
just slot 0.** `ibgda_create_cq` allocates `num_cqe = round_up_pow2(QP_DEPTH)`
entries (`ibgda.cpp:1487`); here `ncqes = 1024`. New device code scans **every**
64-byte entry of both the RC(peer) and DCI[0] send CQ buffers after the wait. In
baseline, F1, F2b and F3 the opcode histogram is identical: exactly **1** entry
with opcode `0x0` (the one collapsed slot, the last completion) and **1023** at
the `0xf` fill (`0xff`-initialised) — `errs=0`, i.e. **no `0xd`/`0xe` (REQ_ERR/
RESP_ERR) CQE at any index of either CQ, ever** (`scan/*.pe0.log`, `SCAN` lines).
So the error CQE is not hiding in another slot or on the DCI CQ; it is genuinely
never written. The single collapsed slot (`cc=1` at `ibgda.cpp:1537`, `oi=1` at
`:1538`) likewise only ever holds opcode `0x0` across 364 post-wait reads, 45
snapshot transitions and the 38.1 s reference; `wqe_counter` freezes at the last
successful WQE while `ready_head` keeps advancing.

**[measured] The initiator QP state *is* host-observable via QUERY_QP; my earlier
"QUERY_QP is blind" was a mistake and is corrected.** Querying the QP in the same
thread immediately after the `MLX5_CMD_OP_2ERR_QP` returns `state = 6` (ERR),
confirmed both by `DEVX_GET(query_qp_out, out, qpc.state)` and the raw qpc dword
(`0x60001800 >> 28 = 6`). The earlier "state = 3 always" came from the watch
thread racing init, not a bad decode.

**[measured] A confirmed QP-ERR still yields no CQE (the sharpest evidence).**
In **F2b (invalid rkey)** the bad-rkey put draws a responder NAK that drives
**rain's own requester QP to ERR — `QUERY_QP state = 6`** on the exact QPN the put
used (`0x28e4`), sampled *after* the corrupt+put (`ab/F2b_timeout_tcc1_*`), with
`hw_sq_wqebb=15`. So the QP genuinely errors and that error is host-observable —
**yet the full 1024-entry scan of both the RC and DCI CQ shows `errs=0`**, and the
device wait times out with `wqe_counter` frozen. The QP transition happens; the
error completion is simply never written to the CQ.

**[measured] The two faults differ at the QP level.** F2b → QP ERR (state 6);
**F3 (peer QP→ERR, silent drop)** → rain's QP stays `state = 3` (RTS) for all 54
query-only samples over 16 s (`qptl/F3_timeout_t1.pe0.log`, watched QPN `0x27f6`
= the put's QP), while the put stalls and (lead's counters) the wire retransmits
then stops by ≈4 s. F1 (local 2ERR) also drives the QP to ERR (state 6, verified
same-thread post-2ERR query). In **no** case is an error CQE written.

**[rejected] "Infinite RNR retry" is not the explanation for F3.** An earlier
draft attributed F3's RTS-forever to `rnr_retry = 7` (`ibgda.cpp:1976`). The
harness control (verbs QPs, same NICs) shows a peer QP in ERR *silently drops*
and yields RETRY_EXC 12/0x81 at ≈3.7 s — no RNR NAKs — so infinite-RNR does not
fit and is dropped. F3's requester simply does not surface the retry-exhaustion
as a QP-ERR or a CQE on the collapsed CQ within the window; the mechanism for the
missing surfacing is the collapsed CQ (below), not RNR.

**A/B: collapsed (cc=1) vs ring (cc=0) CQ.** New hook switch
`NVSHMEM_IBGDA_FAULT_CQ_COLLAPSED=0` creates the CQ with `cc=0`, everything else
identical; ITERS=1 with the fault landing on the first put.

| CQ mode | reaches init "ready" | put runs | error CQE in full buffer |
|---|---|---|---|
| cc=1 (stock, collapsed) | 12/12 | yes | **none** — baseline/F1/F2b/F3, `errs=0` in 1024 entries |
| cc=0 (normal ring) | **0/12** | no | n/a — NVSHMEM init hangs |

**[measured] cc=0 is not drivable inside IBGDA.** With `cc=0`, NVSHMEM init hangs
before "ready" in every trial (`ab/*_tcc0_*`): IBGDA's device completion path
(`ibgda_poll_cq`/`ibgda_quiet`) reads only slot 0 and is written for the collapsed
CQ, so an init-time device barrier never completes on a ring CQ. Flipping `cc`
therefore cannot give an in-stack A/B of error-CQE delivery. The ring-CQ
comparison comes from the sibling stack instead: NCCL GIN **GDAKI** uses a normal
ring CQ on the *same* NICs and *does* receive error CQEs (its blocking flush
returns on a failed write; its host QP-state check sees the error) — so the NIC
does deliver error completions to a ring CQ; IBGDA's collapsed CQ does not show
them. That the collapsed CQ is *the* reason was thus only **[inferred]** here, not
provable by flipping `cc`.

**[rejected, 2026-09-23] "The collapsed CQ is the reason."** The in-stack A/B was
then done in NCCL GIN GDAKI, whose bundled DOCA GPUNetIO supports both CQ shapes
(`../gin_q4/`, Task A). On the same NICs and firmware a collapsed CQ in GPU memory
**does** receive error CQEs: the device poll returned -EIO in 27/27 collapsed
F1/F2/F3 trials, slot 0 held the root-cause CQE (5/0xf5, 10/0x88, 12/0x81) at
poll time and the trailing flush 5/0xf9 500 µs later. So the collapsed CQ as such
does not suppress error completions, and why no error CQE ever appears in
NVSHMEM's CQ remains **open**. Differences worth checking next: the CQ and QP
context bits NVSHMEM sets through DEVX versus DOCA's (dump both with QUERY_CQ /
QUERY_QP and diff), and the two CPU-proxy doorbell paths (NVSHMEM's
`ibgda_rc_progress` versus DOCA's, which in collapsed mode also needs
`CPU_PROXY_UPDATE_PI`).

**[measured] The CQ cannot be relocated to host memory here.**
`NVSHMEM_IBGDA_FORCE_NIC_BUF_MEMTYPE=hostmem` fails at init on this box
(`cudaHostRegister … IoMemory failed error=800`; no gdrdrv, driver predates the
CUDA DMA-BUF path), so a GPU-vs-host CQ-delivery comparison could not be run.

**[measured] CE bits do not explain the absence.** In
`nvshmemi_ibgda_put_signal_thread_impl` the RDMA-write WQE is unsignaled and only
the trailing atomic carries `MLX5_WQE_CTRL_CQ_UPDATE` (`ibgda_device.cuh:3367`),
but IB error completions are delivered regardless of the CE bit.

**Conclusion.** In this configuration a GPU thread polling the IBGDA send CQ has
no path to observe a requester error: no `0xd`/`0xe` CQE is written to any of the
1024 entries of the RC or DCI CQ for any fault, **even when the requester QP is
confirmed in ERR (F2b)** **[measured]**. The QP *state* is host-observable
(QUERY_QP) — F1/F2b reach ERR, F3 stays RTS **[measured]** — but that is a
host-side DEVX query, not something the GPU poller consults, and IBGDA installs no
async-event/EQ handler (`ibgda_create_cq` allocates a UAR/EQ but `:1523` notes
"IBGDA never uses it") **[measured/observed in source]**. Flipping the CQ to a
normal ring (cc=0) to test delivery directly is not possible in-stack (init hangs)
**[measured]**. The cross-stack A/B in GDAKI showed that both ring and collapsed
CQs receive error CQEs on the same NICs, so the collapsed CQ is **not** the reason
and the cause of the missing error CQEs in NVSHMEM is **open** (see above). The only
device-visible symptom of any fault is **stalled progress** — `wqe_counter` frozen
while `ready_head` advances — which a bounded wait can detect but cannot classify.
This holds identically for a prompt remote
error (F2b invalid rkey), not just retry-exhaustion faults.

## Observations

- **The error code is never visible at the IBGDA device CQ.** Across every fault and wait mode, the
  collapsed slot the device polls holds only normal completions; the WR_FLUSH / REM_ACCESS /
  RETRY_EXC CQEs that CPU verbs produce (`../cqe_seq/`) are absent. Evidence: `matrix.csv` (all
  `cqe_opcode=0x0`), `snap/*.pe0.log` (all `op=0x0`), `matrix_ref.csv` (op 0x0 at 38.1 s). This is
  the central negative result: device-side classification (as in the GDAKI device-side classifier)
  has nothing to classify for these faults on this stack — the only device-observable signal is
  stalled progress (`wqe_counter` frozen).

- **Why the flush prediction of `../cqe_seq/` does not reproduce here.** See the Root-cause
  section: the NIC does reach retry exhaustion (wire counters), but the resulting
  requester error CQE is never delivered to the collapsed CQ the GPU polls, the
  CQ exposes no producer counter, and QUERY_QP does not report ERR. (The earlier
  claim that the op "never retires" is **superseded** — it retries then gives up;
  it is the completion's *delivery/visibility* that is missing.) For the *local*
  fault (F1), ms-granularity injection also lands between ops, so the next post
  hits an already-ERR QP dropped by the CPU-proxy doorbell; the burst-16 snapshot
  (`snap/F3_snapshot_t2`) shows 16 puts completing as normal CQEs in the first
  microseconds, then the slot goes static for the rest of the 15 s.

- **Blocking wait = silent, unbounded hang.** `nvshmem_quiet()`'s `ibgda_poll_cq`
  spins on `wqe_counter`; with the on-error `assert` compiled out (NDEBUG,
  confirmed) it can only ever return "success" or spin forever. For every fault it
  spun until our host watchdog killed the process (teardown `hang`). It never
  reported an error and never returned an error code — matching the DESIGN's
  prediction that the blocking path "discards" the error / hangs.

- **F2a (`oob_within_mr`) is a silent data-integrity violation, not a
  NIC-level REM_ACCESS** (relabelled per QA — a write that stays inside the single
  registered heap MR is one the NIC legitimately performs). A put one window past
  the destination gets a valid rkey to the wrong in-heap offset (the device bounds
  `assert` in `ibgda_get_raddr_rkey` is compiled out): the initiator's wait returns
  success (`init_outcome=ok`, no error CQE) while the peer's data is wrong —
  `silent_success=1` in all 3/3 trials of every mode. A *far* overrun (256 MiB,
  past the whole heap) instead indexes the device rkey array out of bounds and
  raises an illegal-memory-access on the GPU (context lost), still never a
  REM_ACCESS CQE.

- **F2b (invalid rkey) — a genuine remote error — is also invisible.** Corrupting
  all 64 `constmem.rkeys` entries makes the next put carry a bad rkey; the put
  fails (PE1 `data_check=missing`, `wqe_counter` frozen) but the collapsed slot
  still reads `opcode 0x0`, the bounded wait times out (≈3.85 s), and teardown
  hangs — identical signature to the retry-exhaustion faults. So even a prompt
  remote NAK never surfaces as an error CQE to the GPU (`matrix_f2b.csv`,
  `f2b/*.pe0.log`).

- **Teardown does not return after a QP error.** For F1/F2b/F3/F4,
  `nvshmem_finalize` itself hangs (it tries to quiesce the broken QP); the
  driver's 15 s finalize watchdog exits 7. Only the baseline and F2a tear down
  cleanly.

- **Timeout / DeepEP waits detect the stall but cannot classify it.** Our own
  bounded `clock64` poll (timeout mode) and the wqe_counter-only DeepEP-style poll
  both correctly return "not complete" at the budget (host learns at ≈1.5 s for
  F1, ≈5.8 s for F3/F4). Neither can say *why*, because the CQ carries no error.
  The DeepEP poll would take an error CQE as success if one ever appeared, but one
  never does — so here it degenerates to the same timeout.

- **Host learns only via our own bound.** There is no async-event handler and no
  API that surfaces the QP error; the host learns a fault happened solely because
  our device wait timed out or our watchdog fired, never from NVSHMEM.

## Limitations

- Only the **CPU-with-host-memory** NIC handler is reachable here (no
  PeerMappingOverride / gdrdrv), so the GPU cannot ring the doorbell itself; a
  CPU proxy does. The device poll / quiet code under test is identical to the
  GPU-doorbell case, but doorbell timing differs.
- ms-scale host fault injection almost always lands **between** device
  operations, so for a local QP→ERR (F1) the next post hits an already-ERR QP and
  is dropped by the proxy with no CQE at all; a genuine in-flight flush is only
  observable when WQEs stay outstanding in hardware for a long window (F3/F4,
  where the retry timer holds them ≈3.7 s at IB_TIMEOUT=14).
- Symmetric/registered memory is kept ≤ 64 MiB (BAR1 = 256 MiB). DeepEP itself
  needs SM90 and cannot run on this hardware; only its poll style is reproduced
  (`deepep_poll`).
- `NVSHMEM_DISABLE_CUDA_VMM=1` is required for heap registration here; the
  device data-path code is unchanged by it.
- **Diagnostic-tooling notes.** (a) `QUERY_QP` is accurate (verified: `state = 6`
  ERR immediately after `2ERR`, raw dword confirms) — the earlier "returns RTS
  always" was a watch-thread-vs-init race, now fixed with a query-only mode and a
  startup delay (`NVSHMEM_IBGDA_FAULT_WATCH_QPONLY` / `_DELAY_MS`). (b) `QUERY_CQ`
  producer/consumer stay 0 even for successful traffic, consistent with the
  collapsed CQ (`cc=1`) using only slot 0 (the full-buffer scan confirms 1 live
  entry / 1023 fill). (c) The `FAULT_WATCH` *per-period `cudaMemcpy` slot dump*
  perturbs a faulting run and read an unused loopback ep's CQ; use query-only
  watching for QP state, and the driver's device `read_cqe` + full-buffer `SCAN`
  as the authoritative CQE probes. (d) Host-memory NIC buffers
  (`FORCE_NIC_BUF_MEMTYPE=hostmem`) fail to initialize here, so the GPU-vs-host
  CQ-delivery comparison could not be run.
