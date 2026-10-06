# teardown_order: 상세 기록

아래는 예전 README 본문을 그대로 옮긴 것이다(영문). 요약은 [README.md](README.md)에 있다.

**2026-10-06 리뷰 정정**
- "커널이 verbs 객체를 지우는 순서가 정한다"로 줄이면 과장이다. 순서는 필요조건이고 결과는 경쟁이다. 호스트 8 MiB MR을 QP 뒤에 등록하면 0x88은 sunny 1/10, rain 7/10이었다. DEVX QP를 먼저 지우는 규칙은 OFED 25.10에만 있다.
- 응답 쪽 커널 로그 줄 수(본문 C절)는 원본 파일이 레포에 없어 다시 셀 수 없다.
- 본문의 0/83, 111/192, 111/161(sunny DEVX 31회)은 스모크 kill 5회를 섞은 값이다. kill 270회만 세면 MR 먼저 0/80, MR 나중 111/190, sunny DEVX 30회를 빼면 111/160이다. README는 270회 기준으로 적었다.
- 본문 Answer 4번의 "sunny 3/30, rain 15/20"은 변형을 합친 값이다. sunny는 기본 1/10, RNR 타이머 2/10, 카운터 0/10이고, rain은 일반 QP 7/10, DEVX QP 8/10이다.
- 본문 C절의 "35 REM_ACCESS kills on rain"은 GPU peermem만이 아니라 rain의 0x88 kill 전체(GPU 20회, 호스트 15회)다.
- 아래 본문에 이미 반영된 정정: fd 순서와 GPU 메모리 해제 가설 기각, 첫 스모크 세션(`superseded_smoke1_underflow`) 폐기.

The review question: the same fault, "peer process killed with SIGKILL", gives the initiator
different error codes.
* RETRY_EXC 12/0x81 after ~3.7 s in the CPU verbs harness (`retry_proc_kill`, host-memory
  MR), with NVSHMEM IBGDA, and with GIN GDAKI.
* REM_ACCESS 10/0x88 after ~60 ms with NCCL GIN's proxy backend (target in GPU memory;
  `../gpu-initiated/gin/README.md`, `../gpu-initiated/RESULTS.md` finding 7).

Does that break "the CQE alone classifies"? What is the mechanism?

The hypothesis to test was this. At exit the kernel closes fds in ascending order. The CUDA
fds, opened first, go first, and GPU memory is freed. nvidia_peermem then invalidates the GPU
MR while the QP is still alive, and the next WRITE is NAKed.

Tags: **[measured]** (this directory; raw data in `results/20260925/`), **[source]** (code read
on these machines), **[inferred]**. 417 trials, all run under
`../gpu-initiated/common/cluster_run.sh`, N=10 per variant (7 single smoke trials besides).
A one-off recount of every trial from the raw requester and victim logs found 0 mismatches
(`qa_crosscheck.py`, removed 2026-10-06, in tag `archive/results-tables-20261006`).

## Answer

1. **The hypothesis is wrong on this system. Neither fd order nor GPU memory being freed
   decides the error code.**
   * Opening CUDA before or after `ibv_open_device` changed nothing. GPU/peermem with the MR
     registered after the QP gave REM_ACCESS 10/10 either way. With the MR registered before
     the QP it gave RETRY_EXC 10/10 either way [measured].
   * The QP was left up while the registered GPU buffer was freed (`cudaFree`) or the whole
     CUDA context was destroyed (`cudaDeviceReset`). That produced **no error at all**:
     20/20 with peermem, 10/10 with dma-buf. The NIC went on completing ~74 000 64 KiB WRITEs
     per trial into that memory for the 1.5 s observed [measured].
   * nvidia_peermem on these drivers registers only its *persistent* client, which pins the
     pages and has no invalidation callback [source]. The mechanism in the hypothesis would
     need the legacy invalidating client (`persistent_api_support=0`). Switching to it needs a
     module reload, so it was not tested.
   * The kernel releases a dying process's fds in **descending** order, not ascending
     (275/275 kill trials) [measured, source].
   * In a CUDA process the uverbs file is released **after every fd**, whatever its number:
     ~39 ms after the kill on sunny, after all CUDA files (142/142) [measured]. Its last
     reference is a memory mapping, and nvidia-uvm keeps the address space alive until its
     own fd is released [source, inferred].
2. **The error code depends on which of the dead process's verbs objects is destroyed
   first: the QP the WRITEs arrive on, or the MR they target.**
   * QP first: the QPN is gone, the NIC drops the requests silently, and the requester retries
     until RETRY_EXC 12/0x81, 3.5-3.8 s after the last ACK.
   * MR first while the QP still answers: the responder NAKs, and the requester gets
     REM_ACCESS 10/0x88.
   * On a live process the same holds. `ibv_dereg_mr` gave REM_ACCESS 90/90 and
     `ibv_destroy_qp` gave RETRY_EXC 20/20 [measured].
   * Over all kill trials, the MR registered *before* the QP gave REM_ACCESS 0/83. The MR
     registered *after* the QP gave REM_ACCESS 111/192 [measured], but that pools two mechanisms:
     31 of the 192 are DEVX-QP trials on sunny, where OFED 25.10 destroys every DEVX QP before
     anything else, so REM_ACCESS cannot occur there (0/31). Without them, MR-after-QP kills gave
     REM_ACCESS **111/161**; the rest is the race described below. The order claim itself rests on
     the paired cells (0/10 vs 10/10, 0/20 vs 20/20) and the kernel source.
3. **Registration order and QP flavour set which object dies first.**
   * The uverbs file destroys its objects newest first (`list_add` at the head, walk from the
     head), so an MR registered after its QP dies before it [source].
   * The exception is sunny's OFED 25.10. There, `mlx5_ib_ufile_hw_cleanup` destroys every
     **DEVX QP** before anything else [source]. GDAKI (DOCA verbs) and NVSHMEM IBGDA create
     their QPs as DEVX objects [source]. On sunny, a DEVX QP with the GPU MR registered after
     it gave RETRY_EXC 10/10, against REM_ACCESS 40/40 with a verbs QP.
   * rain's OFED 23.10 lacks that hook. With the victim on rain, the same DEVX victim gave
     REM_ACCESS 10/10 [measured].
4. **MR-first is necessary but not sufficient: it is a race.**
   * After an MR is revoked, the responder answers the next WRITE to it only after a delay,
     with no ACK and no NAK in between. The delay was 1.0-1.1 ms on rain and in sunny's later
     sessions, and ~2.2 ms in two earlier sunny sessions [measured, live `dereg_mr`].
   * The delay is not RNR pacing: the responder's RNR timer (0.01 or 2.56 ms) did not change
     it. It is not requester retransmission either: the requester's adaptive-retransmit,
     ack-timeout and sequence-error counters stayed at 0 before the NAK (20/20) [measured].
   * REM_ACCESS gets out only if the dying process destroys the QP later than that.
     Lengthening the MR-to-QP gap flips the outcome [measured]:
     * a host 8 MiB MR registered right after the QP gives REM_ACCESS 3/30 on sunny and 15/20
       on rain;
     * 1 GiB instead of 8 MiB (slower unpin) gives 10/10, and 32 other MRs registered between
       QP and MR give 10/10;
     * dma-buf gives 0/10 alone and 10/10 with 32 MRs in between;
     * peermem GPU memory gives 40/40 on sunny and 20/20 on rain.
   * A live deregistration takes 0.07 ms (dma-buf), 0.13-0.26 ms (host 8 MiB) and
     0.56-0.96 ms (peermem), which matches that ordering. The in-kernel teardown itself was not
     timed [inferred].
5. **The three stacks, explained.**
   * **CPU harness `retry_proc_kill`**: this is not a SIGKILL. The server calls `ep_close()`
     (QP destroyed first) and returns, and the client posts 300 ms later [source]. A real
     SIGKILL mid-stream, in the harness's registration order, also gives RETRY_EXC 10/10
     [measured].
   * **GDAKI and NVSHMEM IBGDA**: they use DEVX QPs, and sunny destroys those first. RETRY_EXC
     follows [source; measured analogue].
   * **GIN proxy**: it uses verbs QPs, connects them in `createContext`, and only *then*
     allocates and registers its GPU signal buffer [source]. An MR newer than the QPs dies
     first, so REM_ACCESS is possible [inferred]. The ~60 ms fits a CUDA process, whose uverbs
     file is released last: 39.5-41.7 ms in our minimal peermem CUDA victims on sunny,
     31-33 ms on rain [measured analogue].
6. **So 10/0x88 alone does not name the cause.** It says "the target MR was gone while the QP
   still answered". A live peer produces that through an application bug (bad rkey or
   offset, early `ibv_dereg_mr`). A dead peer produces it while it is being torn down. The
   decision (decline) is the same, but the diagnosis differs, and liveness is needed exactly
   as for 0x81. In all 270 kill trials the peer's OOB socket delivered its FIN before the first
   error CQE, but in plain processes by as little as 0.43 ms [measured]. The rule is in
   [Classification rule](#classification-rule).

## Results

`victim` is the node of the killed or acting process. The requester is always the other node.
Times are ms after the trigger (the SIGKILL, or the start of the `ACT` call), on the victim's
clock (offset by min-RTT ping, RTT 0.10 ms), as median [min-max]. "last ACK" is the last
successful WRITE completion. "OOB FIN" is when the victim's OOB TCP socket delivered EOF at
the requester.

Variant names:
* `host`/`gpu`/`dmabuf`: the MR memory (gpu = cudaMalloc + `ibv_reg_mr` via nvidia_peermem).
* `mrfirst`/`qpfirst`: MR registered before/after `ibv_create_qp`.
* `cudafirst`/`ibvfirst`: CUDA context before/after `ibv_open_device`.
* `devx`: the QP is a DEVX object.
* `x32`: 32 extra 4 MiB host MRs between QP and data MR. `1g`: 1 GiB data MR.
* `rnr1`: responder RNR timer 0.01 ms. `cudahost`: host MR in a process with a CUDA context.
* `cnt_`: with requester HW counters. `rev_`: victim on rain. `ctl_`: explicit teardown while
  alive.

| victim | variant | trigger | N | first error CQE | error ms | last ACK ms | OOB FIN ms | reaped ms |
|---|---|---|---|---|---|---|---|---|
| sunny | `host_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3639.5 [3615.8-3642.1] | 0.63 [0.59-0.69] | 0.59 [0.56-0.65] | 2.2 [2.2-2.5] |
| sunny | `host_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **9/10**, REM_ACCESS 10/0x88 **1/10** | RETRY 3638.0 [3514.3-3641.3]; REM 2.5 [2.5-2.5] | 0.57 [0.53-0.76] | 0.60 [0.55-0.78] | 2.4 [2.3-2.6] |
| sunny | `gpu_cudafirst_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3704.9 [3701.2-3708.0] | 39.04 [38.77-39.37] | 0.16 [0.16-0.17] | 73.9 [73.1-75.3] |
| sunny | `gpu_cudafirst_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 41.2 [40.3-41.4] | 39.00 [38.73-39.31] | 0.16 [0.15-0.17] | 74.6 [73.3-76.5] |
| sunny | `gpu_ibvfirst_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3704.9 [3578.3-3708.7] | 39.27 [38.85-39.64] | 0.17 [0.16-0.18] | 74.2 [73.9-76.5] |
| sunny | `gpu_ibvfirst_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 41.3 [40.3-41.7] | 39.02 [38.56-39.42] | 0.16 [0.15-0.17] | 74.7 [74.0-75.2] |
| sunny | `dmabuf_cudafirst_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3702.4 [3545.7-3708.7] | 39.23 [38.90-39.86] | 0.16 [0.15-0.20] | 73.9 [73.7-76.8] |
| sunny | `dmabuf_cudafirst_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3706.2 [3701.1-3708.4] | 39.18 [38.73-39.60] | 0.16 [0.15-0.17] | 74.7 [74.2-76.6] |
| sunny | `host_qpfirst_x32` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 5.0 [4.3-6.8] | 3.90 [3.22-4.63] | 3.91 [3.23-4.65] | 15.9 [14.8-17.9] |
| sunny | `dmabuf_qpfirst_x32` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 44.0 [43.4-44.7] | 43.00 [42.43-43.62] | 0.17 [0.16-0.19] | 88.7 [86.6-91.1] |
| sunny | `host_qpfirst_1g` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 22.6 [21.8-23.6] | 21.34 [21.11-21.60] | 21.37 [21.11-21.62] | 101.5 [98.8-104.3] |
| sunny | `host_qpfirst_rnr1` | kill | 10 | RETRY_EXC 12/0x81 **8/10**, REM_ACCESS 10/0x88 **2/10** | RETRY 3635.4 [3513.3-3639.7]; REM 1.2 [1.0-1.4] | 0.58 [0.51-0.62] | 0.60 [0.54-0.64] | 2.4 [2.2-2.6] |
| sunny | `gpu_qpfirst_rnr1` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 40.1 [39.5-40.3] | 39.05 [38.88-39.53] | 0.17 [0.16-0.17] | 74.4 [73.7-76.2] |
| sunny | `cudahost_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **7/10**, REM_ACCESS 10/0x88 **3/10** | REM 30.9 [30.7-31.0]; RETRY 3685.6 [3646.9-3771.4] | 30.18 [29.70-31.47] | 0.17 [0.17-0.59] | 64.1 [63.5-67.0] |
| sunny | `host_mrfirst_1g` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3770.3 [3731.8-3775.6] | 20.28 [20.17-21.20] | 20.22 [20.09-21.14] | 96.9 [96.0-97.8] |
| sunny | `cnt_gpu_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 40.2 [39.8-40.8] | 39.27 [38.86-40.06] | 0.17 [0.14-0.17] | 75.0 [74.6-78.1] |
| sunny | `cnt_host_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3635.8 [3553.1-3637.9] | 0.58 [0.53-0.63] | 0.60 [0.56-0.66] | 2.4 [2.2-2.5] |
| sunny | `cnt_host_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3635.0 [3618.4-3638.4] | 0.65 [0.59-0.71] | 0.61 [0.56-0.67] | 2.3 [2.2-2.5] |
| sunny | `devx_host_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3636.4 [3613.7-3646.9] | 0.67 [0.61-0.71] | 0.63 [0.58-0.67] | 2.3 [2.2-2.5] |
| sunny | `devx_host_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3639.1 [3619.0-3641.3] | 0.66 [0.61-0.72] | 0.63 [0.58-0.67] | 2.2 [2.1-2.3] |
| sunny | `devx_dmabuf_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3706.3 [3685.2-3708.2] | 39.39 [39.00-40.74] | 0.16 [0.15-0.18] | 74.5 [73.7-78.6] |
| sunny | `devx_gpu_qpfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3702.2 [3683.7-3707.2] | 39.14 [38.81-39.46] | 0.16 [0.16-0.17] | 73.9 [73.4-75.6] |
| rain | `rev_host_mrfirst` | kill | 10 | RETRY_EXC 12/0x81 **10/10** | 3728.0 [3542.6-3732.8] | 0.81 [0.73-0.86] | 0.76 [0.69-0.82] | 3.3 [3.2-3.4] |
| rain | `rev_gpu_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 32.2 [31.5-33.4] | 29.93 [29.78-29.96] | 0.19 [0.18-0.20] | 78.3 [78.0-80.6] |
| rain | `rev_host_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **7/10**, RETRY_EXC 12/0x81 **3/10** | RETRY 3719.1 [3626.4-3739.9]; REM 1.8 [1.7-2.3] | 0.70 [0.59-0.79] | 0.72 [0.62-0.81] | 3.3 [3.0-4.2] |
| rain | `rev_devx_gpu_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **10/10** | 31.7 [31.1-32.0] | 29.86 [29.50-30.12] | 0.18 [0.17-0.20] | 78.3 [77.2-79.2] |
| rain | `rev_devx_host_qpfirst` | kill | 10 | REM_ACCESS 10/0x88 **8/10**, RETRY_EXC 12/0x81 **2/10** | RETRY 3656.3 [3586.6-3725.9]; REM 2.6 [2.6-2.7] | 0.72 [0.66-0.76] | 0.73 [0.69-0.77] | 4.0 [3.0-4.4] |
| sunny | `ctl_host_dereg_mr` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 2.2 [1.7-2.4] | - | - | - |
| sunny | `ctl_host_destroy_qp` | destroy_qp | 10 | RETRY_EXC 12/0x81 **10/10** | 3638.3 [3633.2-3712.6] | - | - | - |
| sunny | `ctl_gpu_dereg_mr` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 2.2 [1.9-2.5] | - | - | - |
| sunny | `ctl_gpu_cuda_free` | cuda_free | 10 | none **10/10** | - | - | - | - |
| sunny | `ctl_gpu_cuda_reset` | cuda_reset | 10 | none **10/10** | - | - | - | - |
| sunny | `ctl_dmabuf_cuda_free` | cuda_free | 10 | none **10/10** | - | - | - | - |
| sunny | `ctl_gpu_reset_then_dereg` | reset_then_dereg | 10 | REM_ACCESS 10/0x88 **10/10** | 1.1 [1.0-1.1] | - | - | - |
| sunny | `ctl_host_dereg_rnr1` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 1.1 [0.5-1.1] | - | - | - |
| sunny | `ctl_host_dereg_rnr16` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 1.1 [1.1-1.1] | - | - | - |
| sunny | `ctl_dmabuf_dereg_mr` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 1.1 [1.1-1.1] | - | - | - |
| sunny | `cnt_ctl_host_dereg_mr` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 1.0 [1.0-1.2] | - | - | - |
| sunny | `ctl_devx_destroy_qp` | destroy_qp | 10 | RETRY_EXC 12/0x81 **10/10** | 3637.2 [3615.6-3649.1] | - | - | - |
| rain | `rev_ctl_host_dereg_mr` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 1.1 [0.9-1.1] | - | - | - |
| rain | `rev_ctl_gpu_dereg_mr` | dereg_mr | 10 | REM_ACCESS 10/0x88 **10/10** | 1.1 [0.7-1.1] | - | - | - |

Requester HW counters (`sF_sunny`, deltas from the trigger to the first error CQE) [measured]:
* REM_ACCESS (live `dereg_mr` 10, SIGKILL `gpu_qpfirst` 10): `roce_adp_retrans`,
  `local_ack_timeout_err` and `packet_seq_err` all stayed at 0 in 20/20.
  `req_remote_access_errors` went +1.
* RETRY_EXC (20): `local_ack_timeout_err` +6 and `roce_adp_retrans` +4..+7.

## Mechanism, step by step

### A. How a SIGKILLed process releases its files

* `do_exit` runs `exit_mm()` (kernel/exit.c:863), then `exit_files()` (:871), then
  `exit_task_work()` (:876). `close_files()` walks the fd table upward (fs/file.c:413-443).
  But `fput()` only queues the release with `task_work_add()` (fs/file_table.c:471-494), and
  `task_work_run()` runs that list newest first. Net effect: the **highest fd is released
  first** [source: linux 6.10.8 tree on rain; the victims run 6.8 (sunny) and 5.15 (rain),
  and the 5.4 tree on rain has the same task_work loop].
  * Measured: in 275/275 kill trials (both nodes), the victim's marker sockets closed in
    descending fd order.
* A file's last reference is not always its fd. The victim maps its uverbs file 3-4 times
  (doorbell/UAR pages; `/proc/self/maps`) [measured]. That count was logged in the 330
  victims of sessions sB-sF; s1 predates the logging.
  * **Plain process.** `exit_mm()` tears the address space down first, so the uverbs file is
    released in its fd slot. Measured: in 103/103 sunny non-CUDA kill trials, the responder
    stopped answering between the `after_ibv` and `start` markers. That was 0.5-0.8 ms after
    the kill with 8 MiB MRs, later with 136 MiB-1 GiB MRs, whose unmapping delays everything.
  * **CUDA process.** nvidia-uvm holds an `mm_users` reference on the address space until
    its mm-fd is released (`uvm_release_mm` → `uvm_mmput` = `mmput`; uvm.c:231-247,
    uvm_va_space_mm.c:40-75) [source]. So `exit_mm()` unmaps nothing. The uverbs file
    survives its fd close and is released from the `exit_mmap()` that the UVM fd's release
    triggers, after the remaining fds [inferred from source].
  * Measured for CUDA processes: in 142/142 CUDA kill trials, the responder kept answering
    *after* the lowest-numbered marker (`start`, fd 3) had been released.
    * sunny: `start` at 24.7 ms [18.7-29.2], last ACK 39.1 ms [29.7-43.6], reaped at ~74 ms.
    * rain: `start` at 28.9 ms, last ACK 29.9 ms, reaped at ~78 ms.
    * This held in both fd layouts (CUDA fds below or above the uverbs fd).

### B. What the uverbs release destroys, in which order

* `ib_uverbs_close` → `uverbs_destroy_ufile_hw` → `__uverbs_cleanup_ufile`, repeated until the
  list is empty (OFED 25.10 core/uverbs_main.c:1012-1016, core/rdma_core.c:881-925) [source].
  * Every object was added with `list_add(&uobj->list, &ufile->uobjects)` (rdma_core.c:652),
    i.e. at the head, and the walk starts at the head. Objects are therefore destroyed
    **newest first**.
  * An object still in use (a PD with MRs, a CQ with QPs) is retried on the next pass.
  * MR and QP carry no destroy-order priority in this tree.
* Before that walk, OFED 25.10 calls `ib_dev->ops.ufile_hw_cleanup` (rdma_core.c:891). For
  mlx5 that is `mlx5_ib_ufile_hw_cleanup` (hw/mlx5/devx.c:2685-2735). It destroys every DEVX
  object of type `MLX5_OBJ_TYPE_QP`, and nothing else. So **DEVX QPs die before every MR**
  [source]. The symbol exists in sunny's kernel and not in rain's (OFED 23.10) [measured,
  `/proc/kallsyms`].
* `__mlx5_ib_dereg_mr` (hw/mlx5/mr.c:2261) first stops DMA, by revoking the mkey through UMR
  (`mlx5r_umr_revoke_mr`, umr.c:421-440, `free=1`) or by destroying it. Only after that does it
  release the umem (`ib_umem_release`, mr.c:2316), which unpins host pages or returns
  peer/dma-buf pages [source]. The time spent after the revoke is part of the window in which
  the QP is alive but the MR is gone.

### C. What the requester sees

* **QP gone first.** Nothing answers. RETRY_EXC 12/0x81 arrives 3.51-3.76 s after the last
  ACK (159/159 kill trials that ended so). A live `destroy_qp` behaves the same (verbs 10/10,
  DEVX 10/10) [measured], as does the harness's `retry_server_qp_err` (peer QP error in
  `../gpu-initiated/RESULTS.md`).
* **MR gone first, QP alive.** The responder neither ACKs nor NAKs for a while, then NAKs,
  and the requester gets REM_ACCESS 10/0x88. Delay after a live `dereg_mr`, by session:
  * sunny 2.19 ms [1.70-2.37] (sB) and 2.21 ms [1.90-2.50] (sC);
  * sunny 1.07 ms [0.55-1.11] (sD) and 1.02 ms [1.00-1.18] (sF);
  * rain 1.08 ms [0.69-1.11] (sE).

  Neither the RNR timer nor requester-side retransmission explains the delay (see the
  counters above). Why it was ~2.2 ms in the two earlier sunny sessions is not known.
  In the kill trials the gap from the last ACK to the REM_ACCESS was 0.38-3.51 ms (111
  trials) [measured].
* **Kernel log.** The responder's kernel logs the QP error as
  `mlx5_<n>/1: QP <n> error: local protection error (0x3a 0x0 0x93)`. We matched the lines
  to the variants by their 1 s dmesg timestamps, so a line can land one window off.
  * Live controls: one line per live `ibv_dereg_mr` (91 in total).
  * SIGKILL, REM_ACCESS, host-memory variants with a long window (`x32`, `1g`, `rnr1`,
    `cudahost`): about one line per trial.
  * SIGKILL, REM_ACCESS, GPU-peermem variants: at most 2 lines for the 40 trials on sunny,
    and none for the 35 REM_ACCESS kills on rain.
  * So the responder-side log is no dependable death signal either [measured].
* **Explicit destroy costs** (`ACT` durations in the victim logs, N=10 each) [measured]:
  * `ibv_dereg_mr`: 0.066-0.071 ms (dma-buf 8 MiB), 0.13-0.26 ms (host 8 MiB), 0.56-0.96 ms
    (peermem 8 MiB).
  * Peermem after `cudaDeviceReset`: 0.75-0.90 ms. A destroyed context does not slow it down.
  * `ibv_destroy_qp`: 0.55-0.60 ms. DEVX QP destroy: 0.43-0.48 ms.

### D. GPU memory: no invalidation on this system

* nvidia-peermem 580.178.04 / 570.211.01 with `persistent_api_support=1` (the default)
  registers only the "nc" client, under the name `nv_mem`, with a NULL invalidate callback
  (nvidia-peermem.c:601, 641-660) [source].
  * Its `get_pages` calls `nvidia_p2p_get_pages_persistent` (:501-530), which takes no free
    callback.
  * The invalidating path in the hypothesis runs `nv_get_p2p_free_callback` →
    `ib_invalidate_peer_memory` → mlx5 `mlx5_invalidate_umem` → mkey revoke. It is
    registered only with `persistent_api_support=0`.
  * That setting needs a module reload, so it was not tested here.
* Measured consequences:
  * With the QP up, `cudaFree` (10/10), `cudaDeviceReset` (10/10, 70-75 ms) and dma-buf +
    `cudaFree` (10/10) produced no error. The WRITEs kept completing for the 1.5 s observed.
  * In 142/142 killed CUDA processes, the responder kept ACKing WRITEs after the last CUDA
    file was released: 11-15 ms longer on sunny and 0.9-1.0 ms longer on rain.
  * GPU victims with the MR registered before the QP ended in RETRY_EXC 30/30 (peermem 20,
    dma-buf 10). None saw an invalid rkey.
  * dmesg on both nodes showed no nvidia-peermem message during our sessions. The one NVRM
    `p2p.c:224` assertion on rain (~05:14) fell while another agent held the lock.
* Side finding: a freed CUDA buffer that is still registered remains a live RDMA target. The
  NIC writes into memory the process has freed until the MR is deregistered [measured].
  Presumably the persistent pin keeps the pages from being reused [inferred].

### E. The three stacks

| stack | what dies first at exit | error code | evidence |
|---|---|---|---|
| CPU harness `retry_proc_kill` | the QP. On GO the server calls `ep_close()` itself (QP, CQ, MR, ... in that order, probe.c:293-300) and exits. The client posts 300 ms later (probe_server.c:294-301, probe_client.c:250-254) | RETRY_EXC 12/0x81, 3.73 s | [source]. A real SIGKILL mid-stream with the same MR-before-QP order: RETRY_EXC 10/10 (`host_mrfirst`) [measured] |
| NVSHMEM IBGDA / GIN GDAKI | the DEVX QP. `ibgda.cpp:2390` and `doca_verbs_qp.cpp:747` create QPs with DEVX `CREATE_QP`, and `mlx5_ib_ufile_hw_cleanup` destroys them first on sunny | RETRY_EXC 12/0x81 | [source]. `devx_gpu_qpfirst` / `devx_dmabuf_qpfirst` on sunny: RETRY_EXC 20/20 [measured] |
| NCCL GIN proxy | a GPU MR registered after the QPs. `createContext` connects the verbs QPs (`gin_host_proxy.cc:481` → `ncclIbConnectImpl`/`ncclIbAcceptImpl`, `gin.cc:527-533`), and only then are the signals allocated and registered (`gin_host_proxy.cc:524-533`) | REM_ACCESS 10/0x88, ~60 ms | [source]. Verbs QP + GPU MR after QP: REM_ACCESS 40/40 at 39.5-41.7 ms (sunny) and 10/10 at 31.5-33.4 ms (rain) [measured analogue]. Which MR the failing request hit is unknown. NCCL's WARN prints `opcode=4 len=8`, but libmlx5 does not fill `opcode`/`byte_len` for error CQEs (providers/mlx5/cq.c:875-900), so those fields are stale [source]. Nor do the logs say whether NCCL registered it as dma-buf or peermem. Either can produce REM_ACCESS. A dma-buf MR right after its QP gives RETRY_EXC 10/10, but REM_ACCESS 10/10 once 32 other MRs sit in between (`dmabuf_qpfirst_x32`). NCCL creates further objects between its QPs and the signals MR [inferred] |

On a node with an older OFED (rain, 23.10) the DEVX exception does not apply. A GDAKI or
NVSHMEM peer whose MR was registered after its QPs would then also produce REM_ACCESS
[inferred from `rev_devx_gpu_qpfirst` REM_ACCESS 10/10].

## Classification rule

The CQE error code still says *what the NIC saw*:
* 12/0x81: nobody answered.
* 10/0x88: the target MR was gone or out of bounds while the QP answered.

It does not say *why*. When the answer depends on the peer being alive, the initiator needs
the peer's liveness, for 10/0x88 as already for 0x81. Proposed rule, per failed connection,
evaluated on the root-cause CQE (the first non-flush error; `../gpu-initiated/RESULTS.md`
finding 2):

```
cqe     = first error CQE that is not WR_FLUSH (5/0xf5, 5/0xf9)
dead(P) = the OOB/bootstrap socket owned by peer process P delivers EOF or RST
          by t_cqe + T, or a PROBE on it is still unanswered at t_cqe + T      (T = 1 s)

12/0x81  and local or peer port down   -> LINK_DOWN
12/0x81  and dead(P)                   -> PEER_DEAD
12/0x81  otherwise                     -> PEER_QP_ERR          (QP-level recovery possible)
10/0x88  and dead(P)                   -> PEER_DEAD            (the dying peer's MR went
                                                                before its QP)
10/0x88  otherwise                     -> REMOTE_ACCESS_BUG    (live peer: bad rkey/offset,
                                                                or it deregistered the MR)
```

* **PEER_DEAD is one diagnosis, whichever CQE brought it.** It is declined as peer death,
  not reported as an access bug. That is the change: today `probe.c:classify()` marks
  10/0x88 `peer_alive=true, auto_recoverable=true`, and the GIN device classifier / nvshmem_ft report
  "declined (REM_ACCESS)".
* **Why a bounded wait T and not "FIN already seen".** In 270/270 kill trials the FIN
  arrived before the CQE [measured]. The margin, though, was as small as 0.43 ms (plain
  process, `host_qpfirst_1g`; 30-44 ms in CUDA processes). It also depends on fd layout.
  Fds are released highest first, so a plain process whose OOB socket has a *lower* fd than
  its uverbs file would send the FIN after the uverbs teardown, i.e. after the REM_ACCESS
  [inferred]. A dead peer never answers a PROBE, and a live one answers within an RTT
  (0.1 ms here), so T only costs time when the peer really is dead.
* **Do not use the timing of the NAK.** The silence before the NAK is the same for a dying
  peer and for a live `ibv_dereg_mr` (~1-2 ms) [measured]. Only an out-of-bounds WRITE to a
  valid MR NAKs quickly (0.3 ms, harness `rem_access`, `../gpu-initiated/RESULTS.md`).
* **Apply the same gate to the other remote-NAK classes** (9/0x8a REM_INV_REQ, 11
  REM_OP_ERR), since a dying peer's objects vanish one at a time [inferred, not measured
  here].

## Setup

* **rain**: requester, ConnectX-6 VPI `mlx5_1`, kernel 5.15, MLNX_OFED 23.10.
* **sunny**: victim / responder, `mlx5_0`, RTX A4000, driver 580.178.04 (open kernel
  module), kernel 6.8, OFED 25.10.
* **"rev_" rows**: the victim runs on rain (Quadro RTX 5000, driver 570.211.01) and the
  requester on sunny.
* **Link and QP**: ConnectX-6 VPI fw 20.43.4100, RoCE v2, PMTU 4096, **IB timeout 14,
  retry_cnt 7**, rnr_retry 6, responder min_rnr_timer 12 (0.64 ms) unless `-r`.
* **nvidia_peermem**: loaded on both nodes with `persistent_api_support=1` and
  `peerdirect_support=0` [measured, `/sys/module/nvidia_peermem/parameters`].
* **Runs**: every run went through `../gpu-initiated/common/cluster_run.sh`, one session of
  <= 9 min per lock hold.

Programs (all new; `make` on rain; the victim side is copied to sunny `~/fp-bundle/`):

| file | role |
|---|---|
| `fp_responder.c` | the victim: one RC QP and one MR. See the options below. It logs its fd table and how many mappings of each device file it holds, then waits. `ACT <x>` makes it tear one thing down while it stays alive: `dereg_mr`, `destroy_qp`, `cuda_free`, `cuda_reset`, `reset_then_dereg`. |
| `fp_launcher.c` | runs on the victim's node. It forks the victim and `SIGKILL`s it on request (timestamp taken just before `kill()`), then reaps it through a pidfd. It also timestamps the FIN of every **marker** socket. The victim opens one marker (TCP to the launcher on loopback) after each setup step (`start`, `after_cuda`, `after_ibv`, `after_qp`, `after_mr`, `last`). Each marker is one more file in the victim's fd table, so its FIN times the moment the kernel released that fd. |
| `fp_requester.c` | one trial, in this order: clock offset to the launcher (min-RTT of 32 pings); SPAWN; connect the victim's OOB socket (management network); bring up the QP; stream signaled 64 KiB RDMA WRITEs (<= 8 outstanding, one post per >= 20 us) for 300 ms; trigger. It records the first error CQE (status, vendor_err, time), the last successful completion, the OOB FIN/RST, the launcher's reap and marker times, and (from sF on) its port HW counters. |
| `run_session.sh` | runs a spec (variant, N, trigger, victim flags) under one lock hold. `REVERSE=1` puts the victim on rain. |
| `make_table.py`, `summarize.py` | results table and per-variant summary. |

`fp_responder.c` options:
* `-m host|gpu|dmabuf`: the MR memory.
  * `host`: `aligned_alloc`.
  * `gpu`: cudaMalloc + `ibv_reg_mr`, i.e. through nvidia_peermem.
  * `dmabuf`: cudaMalloc + `cuMemGetHandleForAddressRange` + `ibv_reg_dmabuf_mr`. The fd is
    closed after registration, as NCCL does.
* `-o mr_first|qp_first`: register the MR before or after `ibv_create_qp`.
* `-c none|cuda_first|ibv_first`: create the CUDA context before or after `ibv_open_device`,
  i.e. which files get the lower fd numbers.
* `-q verbs|devx`: create the QP with `ibv_create_qp`, or as a DEVX `CREATE_QP` object as
  DOCA/GDAKI and NVSHMEM IBGDA do (`fp_devx.c`).
* `-B`: MR size.
* `-X n`: register n extra 4 MiB host MRs right before the data MR.
* `-r`: the responder RNR timer.

## Files

| path | what |
|---|---|
| `fp_common.[ch]` | TCP helpers, RoCE v2 GID lookup, verbs RC QP bring-up (timeout 14, retry 7, rnr_retry 6) |
| `fp_responder.c`, `fp_devx.[ch]` | the victim; DEVX RC QP (1-WQEBB SQ, zero-length RQ, host umem, address path from an `ibv_ah`) |
| `third_party/mlx5_ifc.h` | PRM layouts, verbatim from rdma-core `providers/mlx5/mlx5_ifc.h` (dual BSD/GPL) |
| `fp_launcher.c`, `fp_requester.c` | kill/observe side and requester side |
| `Makefile`, `run_session.sh` | build on rain; one locked session per spec |
| `make_table.py`, `summarize.py` | the table above; per-variant summary with marker windows |
| `results/20260925/specs/` | the spec files that were run |
| `results/20260925/s1_sunny` | smoke, fd order, MR/QP order, peermem vs dma-buf (`smoke2_s1.spec`) |
| `results/20260925/sB_sunny` | DEVX QPs; live `dereg_mr` / `destroy_qp` controls (`sB.spec`) |
| `results/20260925/sC_sunny`, `sC_rev_rain` | live GPU controls (`sC.spec`), then the victim on rain (`s5_rev.spec`) in the same lock hold |
| `results/20260925/sD_sunny` | window length (`x32`, `1g`), RNR timer, dma-buf dereg, reset-then-dereg, CUDA+host (`sD.spec`) |
| `results/20260925/sE_rev_rain` | victim on rain: verbs host qp_first, live dereg timing (`sE_rev.spec`) |
| `results/20260925/sF_sunny` | requester HW counters (`sF.spec`) |
| `results/20260925/<session>/trials.csv` | one row per trial (times in ms after the trigger, on the victim's clock) |
| `results/20260925/<session>/logs/req_*.log` | requester log per trial (`[req]` summary line) |
| `results/20260925/<session>/logs/victim_*/` | victim log per trial (config, fd table, mapping counts, `ACT` durations) and the launcher log |
| `results/20260925/<session>/cluster_run.out` | the session's console output under `cluster_run.sh` |
| `results/20260925/superseded_smoke1_underflow/` | first smoke run, **not used**: a requester bug (unsigned underflow) ended every trial immediately |

The programs gained options during the campaign, with unchanged defaults:
* mapping counts in the victim log, `-r`, `-X` and the quoted `victim_fds` column: after s1;
* `reset_then_dereg`: after sC;
* the requester's HW counter columns: after sD.

The sources here are the final versions, and every session used the build current at its
start.

Known quirks: `s1_sunny/trials.csv` wrote `victim_fds` without quotes, so CSV readers see only
its first entry (fixed before the later sessions; the full fd table is in each victim log). The
victim options `-U`/`-V` (dup the uverbs / nvidia fds to other numbers) exist but were **not
used** in any reported run, because the fd-order question was settled without them.

Reproduce (from this directory, on rain):

```
make
../gpu-initiated/common/cluster_run.sh -w 3600 -t fp -- ./run_session.sh <out> results/20260925/specs/<spec>
REVERSE=1 ../gpu-initiated/common/cluster_run.sh -w 3600 -t fp-rev -- ./run_session.sh <out> results/20260925/specs/s5_rev.spec
python3 summarize.py <out>/trials.csv
```


