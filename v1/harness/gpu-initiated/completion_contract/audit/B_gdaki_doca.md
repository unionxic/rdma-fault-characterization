# B: NCCL GIN GDAKI and DOCA GPUNetIO, DBR send-counter audit

Rule under test (from the caller): on ConnectX-6, after a QP error the NIC produces completions only for
WQEs from the first incomplete one up to the DBR send value (word 1); WQEs at or above the DBR get none,
even if already executed; raising the DBR later produces them. So a stack shows faults at the CQE layer
only if its DBR send value eventually reaches the posted index.

Labels: [read] = read in source at the cited lines. [inferred] = follows from the read code plus the rule,
not run. [unverified] = could not be settled from source.

## Sources

| Id | What | Version |
|---|---|---|
| N: | github.com/NVIDIA/nccl, newest public tag | `v2.32.3-1`, commit `12df1a11afad322be5a204a2db890161cbf8131d` (2026-09-17). Clone: `audit/src/nccl-v2.32.3` |
| D: | DOCA GPUNetIO vendored in NCCL | `N:src/transport/net_ib/gdaki/doca-gpunetio/` (same commit) |
| G: | github.com/NVIDIA-DOCA/gpunetio (public open-source GPUNetIO) | `main` = `b2b7a291ec70fdeeb1b27ba4b0ab8c8e260a729b` ("v5.0.0 rc1", 2026-10-05). Clone: `audit/src/gpunetio-main` |
| R: | github.com/linux-rdma/rdma-core (only for row N8) | `master` `bd3282a1cf1025c7869a8664c2d54266a4dded44` |

- [read] `D:include/device/doca_gpunetio_dev_verbs_{qp,cq,counter}.cuh` and `D:include/common/doca_gpunetio_verbs_dev.h`
  are byte-identical (sha1) to the `G:` copies, so every device-side line number below is valid for both.
  The CPU-proxy progress functions in `D:src/doca_gpunetio.cpp` match `G:src/doca_gpunetio.cpp:1358-1510`
  except two `COMPILER_EXPECT` wrappers.
- [inferred] NCCL vendors a pre-5.0 GPUNetIO (its `doca_gpu_verbs_export_qp` lacks the `cq_rq`/`dbr_cpu_ptr`
  arguments that `G:CHANGELOG.md` lists for 5.0.0), roughly 4.1.x.
- Not audited: the closed DOCA SDK (`libdoca_gpunetio.so`). NCCL uses it only if the SDK libraries load
  (`D:src/doca_gpunetio.cpp:136-147`). The earlier rain run used the open path:
  `scratchpad/gi/gin_q4/dbg_host_r0_log.txt:17-18` "DOCA SDK is not in use ... Use DOCA GPUNetIO open".

## Facts common to every GPU-side row

- DBR word [read]: `qp_cpu_->sq_dbrec = (__be32 *)(dbrec + DOCA_GPUNETIO_IB_MLX5_SND_DBR);` with
  `DOCA_GPUNETIO_IB_MLX5_SND_DBR = 1` on a `uint32_t *`, i.e. word 1 (byte offset 4)
  (`D:src/doca_gpunetio.cpp:877`, `D:include/common/doca_gpunetio_verbs_def.h:249-250`).
  The value is `htobe32(pi & 0xffff)`: PTX `and.b32 ...,0xffff; prmt.b32 ...,0x123` (`qp.cuh:252-272`), CPU
  `htobe32(new_pi & 0xffff)` (`D:src/doca_gpunetio.cpp:1239`, `:1269`). The GPU store is
  `cuda::atomic_ref<uint32_t, cuda::thread_scope_system>.store(relaxed)` (`qp.cuh:280-286`).
  The wrong-word defect class of NVSHMEM 3.5.x-3.8.0 is absent here.
- UAR doorbell [read]: an 8-byte ctrl segment, `qpn_ds` plus `opmod_idx_opcode = bswap32(pi << 8)`
  (`qp.cuh:339-350`), written with `st.mmio.relaxed.sys.global.b64` when CUDA >= 12.2 (`qp.cuh:359-384`,
  `common.cuh:140-145`).
- In every DOCA submit path the order is DB first, DBR second, then DB again. The code comment at
  `qp.cuh:534-538` says: "Early rining of the DB to push WQEs to the NIC ASAP. / In case the recovery
  path is triggered, the later DB ringing will cover for correctness."
- NCCL CQ mode [read]: `memset(&qp_init_attr, 0, ...)` (`N:src/transport/net_ib/gdaki/gin_host_gdaki.cc:787`)
  leaves `cq_type = 0 = DOCA_GPUNETIO_VERBS_CQ_64B` (`verbs_def.h:373-374`): a non-collapsed CQ in GPU memory.
  In that mode every WQE gets `CQ_UPDATE`, even with SKIP_DB_RINGING (`qp.cuh:129-144`), so each WQE has its
  own CQE slot.
- NCCL knobs [read], all in `gin_host_gdaki.cc`: `NCCL_GIN_GDAKI_NIC_HANDLER` (default 0 = AUTO, `:57`,
  passed through at `:792`); `NCCL_GDAKI_USE_RELIABLE_DB` (default 0 = VALID_DBR, `:585`, `:794-796`;
  fallback chain HW, then SW emulation, then VALID only if the value is 2, `:803-816`, `:839-852`);
  `NCCL_GIN_GDAKI_QP_DEPTH` (default 128, `:58`).
- AUTO resolution [read]: the handler becomes GPU_SM_DB if `cudaHostRegister(UAR, ...IoMemory)` succeeds,
  otherwise CPU_PROXY (`D:src/doca_gpunetio.cpp:654-678`, `D:src/doca_gpunetio_high_level.cpp:1406-1427`).

## Table 1: NCCL GIN GDAKI backend (v2.32.3-1)

| # | Mode (how selected) | Q1 WQE builder / doorbell | Q2 DBR write: who, where, word, memory | Q3 order and fences | Q4 can DBR lag permanently? | Q5 prediction after QP error | Q6 evidence |
|---|---|---|---|---|---|---|---|
| N1 | **GPU_SM_DB**: NCCL default (AUTO with a GPU-mappable UAR, or `NIC_HANDLER=2`), VALID_DBR, CQ_64B | GPU thread (coop rank 0) builds WQEs in the GPU-memory SQ and rings the UAR itself | GPU thread inside `submit_db`, under `sq_lock`, after `atomic_max(sq_wqe_pi)`. Word 1, 32-bit system-scope relaxed store. DBR in GPU memory (UMEM `DOCA_GPU_MEM_TYPE_GPU`; `dbr_is_host_mem` false, `high_level.cpp:1453-1460`) | `mark_wqes_ready`: `fence.release.gpu` + CAS on `sq_ready_index` (`qp.cuh:180-186`). Then lock, `atomic_max`, **DB#1** (no extra fence in GPU sharing mode, `fence.release.gpu` in CTA/thread mode), **DBR store** (no fence), `fence.release.gpu`, **DB#2**, unlock | **No** [read]. Each advance of `sq_wqe_pi` writes the DBR to the new maximum in the same critical section, so the DBR is monotonic. The DBR trails only for the few instructions between DB#1 and the DBR store. Exception: row N4 | **Visible**: every posted WQE gets an error or flush CQE [inferred]. The CQE exists, but NCCL's device API does not report its status (note 1) | `qp.cuh:524-551`: `doca_gpu_dev_verbs_ring_db<sync_scope>(qp, prod_index, code_opt); doca_priv_gpu_dev_verbs_update_dbr<qp_type>(qp, prod_index); ... doca_gpu_dev_verbs_ring_db<second_db_sync_scope>(...)`; dispatch `qp.cuh:659-662`; NCCL put calls `doca_gpu_dev_verbs_put<mode>(...)` with the default handler AUTO (`N:src/include/nccl_device/gin/gdaki/gin_gdaki.h:98-111`) |
| N2 | **CPU_PROXY**: AUTO when the UAR cannot be GPU-registered, or `NIC_HANDLER=1` | GPU builds WQEs (GPU-memory SQ) and publishes the producer index (PI) into one host-pinned, GPU-mapped u64 (`fetch_max`). The NCCL GIN progress thread (CPU) rings the DB | CPU thread, `priv_cpu_proxy_progress_full_assisted`: `htobe32(new_pi & 0xffff)` into word 1 with a `std::atomic<uint32_t>` relaxed store. DBR in host memory (`calloc`/host UMEM, `high_level.cpp:710-716`, `:1454-1457`) | GPU: `fence.release` then a system-scope relaxed store or `fetch_max` to the proxy slot (`qp.cuh:479-490`, `:638-647`). CPU: **DB#1**, **DBR**, `atomic_thread_fence(release)`, **DB#2** (`doca_gpunetio.cpp:1234-1251`) | **Only if the proxy stops** [read]. The DBR trails the GPU PI by proxy latency and catches up on the next pass. `ncclGinProgress` loops until `proxyThreadStopSignal` or a failing `ginProgress` (`N:src/gin/gin_host.cc:56-87`). `ncclGinGdakiProgress` does not look at QP state, so it keeps raising the DBR after a QP error (`gin_host_gdaki.cc:1331-1362`) | **Conditional**: visible while the NCCL GIN progress thread runs. If it stops first (comm destroy or abort), WQEs in (DBR, GPU PI] get none, at most the SQ depth (default 128) per QP [inferred] | `doca_gpunetio.cpp:1238-1251`: `// Ring the DB ASAP. ... sq_db->store(ctrl_seg); sq_dbrec->store(dbr_val); atomic_thread_fence(release); } sq_db->store(ctrl_seg);`. Proxy enable `doca_gpunetio.cpp:935-957`; `needsProxyProgress = need_cpu_proxy` (`gin_host_gdaki.cc:1052`) |
| N3 | **CPU_PROXY_FREE_FLOW** (`NIC_HANDLER=17`) | GPU builds WQEs and sets one ready word per slot (`cpu_db[i & mask] = i+1`). The CPU scans contiguous ready slots and rings the DB | Same as N2 | GPU: `fence.release.gpu`, then per-slot system-scope relaxed stores (`qp.cuh:206-216`). `submit` returns without action (`qp.cuh:669-670`). CPU: up to 64 slots per pass (`DOCA_GPUNETIO_FREE_FLOW_RING_DB_THRESHOLD_DEFAULT`), the loop repeats while it makes progress, then DB/DBR/fence/DB as in N2 (`doca_gpunetio.cpp:1221-1251`) | As N2. In addition, the CPU stops at the first slot that is not ready, so WQEs after a hole are neither rung nor covered by the DBR. That is not DBR lag in the rule's sense, because no DB reached the NIC either. The aggregation hint is ignored | **Conditional**, same condition as N2 | `doca_gpunetio.cpp:1222-1228`: `while (cpu_db[new_pi & wqe_mask].load() == new_pi + 1) { new_pi++; if (... >= threshold) break; }` |
| N4 | **"No doorbell yet" batching**: `ncclGinOptFlagsAggregateRequests` becomes `DOCA_..._SKIP_DB_RINGING`. Takes effect in GPU_SM_DB and GPU_SM_NO_DBR only | GPU builds WQEs and marks them ready, but does not ring | Not written for hinted ops. The next unhinted submit on the same QP writes DBR = its PI, which covers the earlier slots. A flush on a GPU that needs the MCST dump (pre-Hopper or Data Direct, `gin_host_gdaki.cc:1037`) also posts an unhinted dump WQE that covers them (`gin_gdaki.h:315-330`) | None for hinted ops. The covering submit uses the N1 order | **Yes**, if no later unhinted op (or MCST) is posted on that QP [read]. Flush and wait never ring pending WQEs: `flushAsyncImpl` only reads `sq_rsvd_index` (`gin_gdaki.h:333-334`) and then polls. In CPU-proxy modes the hint has no effect (`submit_proxy` never tests SKIP_DB_RINGING, `qp.cuh:638-647`) | **Conditional**: visible if and only if a later unhinted op is posted on the same QP. Otherwise the hinted WQEs after the last unhinted submit get none (count = number of hinted WQEs, at most the SQ depth); they were never executed either [inferred]. The documented pattern (hint on non-final puts only, `N:docs/examples/09_gin_optimizations/README.md:48-51`) meets the condition unless the kernel exits early | `gin_gdaki.h:48`: `(!!(ginOptFlags & ncclGinOptFlagsAggregateRequests) * DOCA_GPUNETIO_VERBS_GPU_CODE_OPT_SKIP_DB_RINGING)`; `qp.cuh:527`: `if (!(code_opt & DOCA_GPUNETIO_VERBS_GPU_CODE_OPT_SKIP_DB_RINGING)) {` |
| N5 | **GPU_SM_NO_DBR, hardware**: `NCCL_GDAKI_USE_RELIABLE_DB=1/2` and the HCA cap `send_dbr_mode_no_dbr_ext` is present | GPU builds WQEs and rings the DB at the "DBR-less" UAR offset (`doca_verbs_qp.cpp:1553-1558`) | **Never written** by design. QPC `send_dbr_mode = 1` (NO_DBR_EXT) (`doca_verbs_qp.cpp:806`; `high_level.cpp:807-814`) | `atomic_max(sq_wqe_pi)`, then DB only, with no lock (`qp.cuh:502-512`) | Not applicable: the hardware is told not to use the DBR | **Visible if** NO_DBR_EXT hardware takes WQE ownership from the doorbell, so the CX-6 DBR rule would not apply [inferred, unverified]. Creation throws NOT_SUPPORTED without the cap (`doca_verbs_qp.cpp:1403-1408`). Whether CX-6 has the cap: [unverified], probably not; NCCL then falls back to N6 (or N1 if the value is 2) | `qp.cuh:502-512` (`submit_db_no_dbr`: `if (old_prod_index < prod_index) doca_gpu_dev_verbs_ring_db<sync_scope>(qp, prod_index, code_opt);`); handler conversion `high_level.cpp:637-640` |
| N6 | **GPU_SM_NO_DBR, software-emulated**: NCCL fallback from N5 when the cap is absent and GDRCopy is present | GPU builds WQEs and rings the UAR DB. The NCCL GIN progress thread (CPU) writes the DBR and rings again | CPU, `priv_cpu_proxy_progress_dbr_assisted`: reads the u64 `sq_wqe_pi` from GPU memory through the GDRCopy mapping (`cpu_db = &qp_gpu_h->sq_wqe_pi`, `doca_gpunetio.cpp:1062-1066`) and stores `htobe32(pi & 0xffff)` to word 1. DBR in host memory | GPU: DB only. CPU later: **DBR**, `fence(release)`, **DB** (`doca_gpunetio.cpp:1263-1274`) | **Structural lag; permanent only if the proxy stops.** Every GPU DB runs ahead of the DBR, so the NIC can execute WQEs above the DBR, which is the exact hazard the rule describes. The lag closes on the next CPU pass | **Conditional**: visible while the progress thread runs; raising the DBR later produces the missing CQEs per the rule. Otherwise WQEs in (DBR, PI] get none (at most the SQ depth per QP) [inferred]. The mode is printed as `reliable_db=SW emulation` (`gin_host_gdaki.cc:859-867`) | `doca_gpunetio.cpp:1263-1274`: `tmp_db = (uint32_t)cpu_db->load(); if (tmp_db != qp->sq_wqe_pi_last) { dbr_val = htobe32(tmp_db & 0xffff); sq_dbrec->store(dbr_val); fence; sq_db->store(ctrl_seg); ...}`; dispatch `:1352-1354` |
| N7 | **GPU_SM_BF** (`NIC_HANDLER=6`) | Host allocates a BlueFlame UAR (`high_level.cpp:103-136`). GPU builds WQEs. NCCL's put/get path calls `doca_gpu_dev_verbs_submit<AUTO>`, whose dispatch has **no GPU_SM_BF branch** | **Never written** | **No DB at all** | Yes, for everything [read: dispatch `qp.cuh:659-670` handles only GPU_SM_DB=2, NO_DBR=10, CPU_PROXY=1, FREE_FLOW=17; GPU_SM_BF=6] | **Lost (all)**, and not only after an error: WQEs never reach the NIC, so the first wait would hang or time out [inferred, not run]. The public DOCA example that uses the same put API rejects this handler: "NIC handler BlueFlame not supported in this example" (`G:examples/gpunetio_verbs_put_bw/gpunetio_verbs_put_bw_main.cpp:89-92`). In practice not a usable NCCL mode | `qp.cuh:659-670`; enum `verbs_def.h:327-342` |
| N8 | **GIN PROXY backend** (not DOCA): NCCL's other GIN backend (`NCCL_GIN_TYPE`, or when GDAKI is unavailable) | CPU proxy thread turns GPU descriptors into `ibv_send_wr` and calls `ibv_post_send`. rdma-core mlx5 builds the WQEs in host memory and rings BF/DB | rdma-core: `qp->db[MLX5_SND_DBR] = htobe32(qp->sq.cur_post & 0xffff);` (word 1, host memory) | `udma_to_device_barrier()`, DBR, `mmio_wc_start`, BF copy or DB, `mmio_flush_writes` (`R:providers/mlx5/qp.c:754-787`): DBR **before** DB | No, for posted WRs. Aggregated WRs stay as host-side `ibv_send_wr` (not yet WQEs) until an unhinted op, a full batch or a QP switch (`N:src/transport/net_ib/gin.cc:461-472`). The proxy hints only when the next descriptor for that peer is already queued and the op is not last (`N:src/gin/gin_host_proxy.cc:249-253`) | **Visible** under the DBR rule [inferred]. Only the last WR of a batch is signaled (`gin.cc:432-434`); whether every unsignaled flushed WR gets its own CQE is outside the rule [not determined] | `gin.cc:428-444`, `R:providers/mlx5/qp.c:769` |

## Table 2: DOCA GPUNetIO device API used directly (public `G:`; identical code in `D:`)

Rows that are the same code as Table 1 are named, not repeated.

| # | Mode / API | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 |
|---|---|---|---|---|---|---|---|
| D1 | `doca_gpu_dev_verbs_submit` with handler GPU_SM_DB (or AUTO resolved to it); also the multi-QP variant used by counters/companion QPs | GPU thread | GPU, word 1, GPU-memory DBR | Same as N1. Multi-QP: DB#1 for every QP, then DBR + `fence` + DB#2 for every QP | No | **Visible**, as N1 | `qp.cuh:524-551`; `counter.cuh:111-193` |
| D2 | `doca_gpu_dev_verbs_submit_bf` (Hopper+, TMA `cp.async.bulk` copies the 64 B WQE from shared memory to the BF register) and `submit_bf_warp` (8 lanes each write 8 B) | GPU thread or warp | GPU, word 1, after the BF write | lock, `atomic_max`, **BF write**, **DBR**, `fence.release`, **DB**. Pre-Hopper `submit_bf` falls back to `submit_db` (`qp.cuh:582-585`) | No. The TMA copy is asynchronous, so the DBR may land before the BF bytes; the final DBR value is unaffected | **Visible** [inferred] | `qp.cuh:565-627`; caller example `G:examples/gpunetio_verbs_write_lat/gpunetio_verbs_write_lat_kernel.cu:113-121` |
| D3 | GPU_SM_NO_DBR with `send_dbr_mode_ext` NO_DBR_HW or NO_DBR_SW_EMULATED | as N5 / N6 | as N5 / N6 | as N5 / N6 | as N5 / N6 | N5: visible if the hardware honors the doorbell [unverified]. N6: **conditional** on the application calling `doca_gpu_verbs_cpu_proxy_progress` (or running `doca_gpu_verbs_create_service`, `doca_gpunetio.cpp:1365-1384`) | as N5 / N6 |
| D4 | CPU_PROXY and CPU_PROXY_FREE_FLOW | as N2 / N3 | as N2 / N3 | as N2 / N3 | Lag lasts until the application's proxy thread runs again | **Conditional** on the application's proxy thread | as N2 / N3 |
| D5 | Device template override: `doca_gpu_dev_verbs_submit<..., GPU_SM_NO_DBR>` on a DBR_VALID QP | GPU | **Never written** | DB only | Yes. Host export rejects the combination (`doca_gpunetio.cpp:791-798`), but the template parameter bypasses `qp->nic_handler` (`qp.cuh:674-676`) | **Lost (all)**: the DBR never moves from its initial value. Misuse path [inferred] | `qp.cuh:671-676` |
| D6 | SKIP_DB_RINGING (application batching) | as N4 | as N4 | as N4 | as N4. In collapsed CQ modes it also clears CQ_UPDATE (`qp.cuh:139-143`) | **Conditional**, as N4 | `qp.cuh:505`, `:527` |
| D7 | CQ type `64B_COLLAPSED_HOST` (not used by NCCL) | depends on the handler | depends on the handler | depends on the handler | DBR as per the handler, but the CPU CQ progress stops at a REQ_ERR CQE without advancing `cqe_ci` (`doca_gpunetio.cpp:1309-1312`, `G:...:1456-1458`). The GPU only watches `cqe_ci` (`cq.cuh:197-204`, `:404-412`) | **Lost at the CQE-to-GPU step** even when the DBR covers everything: the error CQE and all later CQEs exist in host memory, but the GPU never sees them [inferred] | `doca_gpunetio.cpp:1309-1311`: `if (... opcode == DOCA_GPUNETIO_IB_MLX5_CQE_REQ_ERR ...) { DOCA_LOG(LOG_WARNING, "CQE indicates request error"); goto out; }` |

## Notes

1. **NCCL's device API never returns a CQE error** [read].
   - The blocking path (no timeout, no abort flag) calls `doca_gpu_dev_verbs_wait`, which discards the
     `-EIO` from `poll_cq_at` (`onesided.cuh:901-905`). NCCL then returns `ncclSuccess` on an error or flush
     CQE (`gin_gdaki.h:351-357`).
   - The timed and abortable paths accept only `status == 0`, so an error CQE makes them spin until
     `ncclTimeout`, or until abort, which also returns `ncclSuccess` (`gin_gdaki.h:364-377`).
   - `cqe_ci` is not advanced on an error (`cq.cuh:175-180`).

   So in the default mode (N1) the fault reaches the CQE layer but is not passed up as a CQE status.
2. **Host-side error report depends on the CQE in event mode** [read].
   - Call path: `ncclCommGetAsyncError` → `ncclGinQueryLastError` (`N:src/init.cc:3953`) →
     `ncclGinGdakiQueryLastError`, throttled to `NCCL_GIN_ERROR_QUERY_SEC=10` s (`gin_host_gdaki.cc:62`,
     `:1419-1440`).
   - Event mode is used whenever `doca_verbs_comp_channel_create` succeeds (`gin_host_gdaki.cc:772-780`).
     The CQ is armed once with `MLX5_CQ_DB_REQ_NOT_SOL` (`doca_gpunetio.cpp:1690-1711`,
     `high_level.cpp:1492-1503`). An event then needs an error CQE, which by IB solicited-arm semantics
     triggers it [inferred]. With a DBR that never reaches the failed WQE (N2/N3/N6 with a stopped proxy,
     N4 tail, N7, D5), the host would see no event either.
   - Only the polling fallback (`QueryLastErrorPolling`, QP state == ERR, `doca_gpunetio.cpp:1451-1487`)
     is independent of CQEs.
   - The earlier rain log shows the open-path comp-channel creation (`gi/gin_q4/dbg_host_r0_log.txt:26`),
     so event mode was likely in use there [inferred from log].
3. **DB-before-DBR ordering.** Under the rule, a WQE can execute in the gap between DB#1 and the DBR
   store. In N1/D1/D2 the DBR store follows in the same thread with no blocking call in between, and in
   N2/N3 in the same proxy pass, so the gap closes without outside help. In N6 the gap is a full proxy
   round trip.
4. **Fence scope.** The second DB uses `fence.release.gpu`, not `.sys`, between the system-scope DBR store
   and the MMIO doorbell (`qp.cuh:541-546`). Whether that orders the two for the NIC was not analyzed. It
   does not change the final DBR value, which is what Q4/Q5 depend on.
5. **16-bit DBR.** The DBR holds `pi & 0xffff`. The SQ depth is 128 by default, and `reserve_wq_slots`
   waits on the CQ at `idx - nwqes` unless `ncclGinOptFlagsMaySkipCreditCheck` is set
   (`gin_gdaki.h:46-47` maps it to SKIP_AVAILABILITY_CHECK, `qp.cuh:118-120`). With that flag the SQ can be
   overrun. That is a separate hazard from the DBR rule.
6. **Companion QPs** (`nCounters > 0`). `put_counter` posts WAIT(main CQ index) + atomic on the companion
   QP, with the same DB→DBR→DB submit (`counter.cuh:253-334`). Whether an error or flush CQE on the main
   CQ satisfies the WAIT, which would let the counter increment for a failed put, was [not determined].
7. **Self-loop QPs** for the local rank are always created VALID_DBR (`gin_host_gdaki.cc:872-875`) and
   follow N1/N2.

## Could not determine

- Whether ConnectX-6 reports `send_dbr_mode_no_dbr_ext` (decides whether N5 can exist on CX-6), and how
  NO_DBR_EXT hardware completes WQEs after an error.
- The closed DOCA SDK host paths (QP/DBR setup, proxy) used when `libdoca_gpunetio.so` is loadable.
- Whether mlx5 raises a solicited-armed CQ event for flush CQEs as well as for the first error CQE, and
  whether unsignaled flushed WRs (N8) each get a CQE.
- Nothing was run. Every Q5 is a source-based prediction.
