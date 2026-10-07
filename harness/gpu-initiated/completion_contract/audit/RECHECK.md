# RECHECK: independent check of the source evidence for S1-S14

Date: 2026-10-07. Scope: the evidence lines that reports A-D cite for prediction rows S1-S14 in
[../predictions.csv](../predictions.csv), plus the lines each prediction depends on. I did not redo the
whole audit. I built and ran nothing, apart from one `objdump` spot check of the installed libmlx5.

## How the sources were obtained

Each repo was fetched again with `git fetch --depth 1 origin <sha>` at the commit the report names.
`git ls-remote` confirmed that every named tag or branch resolves to that commit today. rdma-core `v47.0`
and rocSHMEM `rocm-7.2.4` are annotated tags, and both peel to the stated commits. gpunetio `main`, DeepEP
`main` and rdma-core `master` are still at the stated heads. The MLNX_OFED fork tarball was downloaded again,
and its sha256 `cb28852c...e333` matches report A. Blobless clones of NVSHMEM and DeepEP were used only for
history checks.

| Repo | Commit used | Report |
|---|---|---|
| linux-rdma/rdma-core | `ccb120c` (v47.0), `bd3282a` (master) | A; B N8, D |
| rdma-core-2307mlnx47 tarball | sha256 `cb28852c` | A |
| NVIDIA/nccl | `68b5423` (v2.23.4-1), `12df1a1` (v2.32.3-1) | A, B |
| NVIDIA-DOCA/gpunetio | `b2b7a29` (main), `f44728f` (pinned by UCX v1.22.0; checked with `git ls-tree`) | B, D |
| NVIDIA/nvshmem | `131da55` (v3.4.5-0), `919760f` (v3.5.19-1), `2c7f5a3` (main 3.5.0-0), `270759e` (v3.8.0-0) | C |
| openucx/ucx | `8a6b06f` (v1.22.0) | D |
| ROCm/rocSHMEM | `61f20f3` (rocm-7.2.4) | D |
| deepseek-ai/DeepEP | `93eb6eb` (main), `a56d615` | C |

## Per-row result

Verdicts: **confirmed** = the file exists, the cited line (within 3 lines) holds the quoted code, and the report reads it correctly.

| Row | Stack | Evidence checked (file:line@commit) | Verdict | Note |
|---|---|---|---|---|
| S1 | libmlx5 verbs, NCCL net_ib, NCCL GIN proxy | rdma-core@ccb120c `mlx5dv.h:69-72`; `qp.c:753-801` (767 barrier, 768 `qp->db[MLX5_SND_DBR] = htobe32(qp->sq.cur_post & 0xffff)`, 774-777, 779-785, 797), `832-847`, `1124`, `1134`, `1142-1144`, `186-199`, `1176-1253`, `1312`, `3536-3563`, `300-311`; `verbs.c:2263-2281`; `cq.c:912,918`; `udma_barrier.h:86,194,235,263-271`; `mlx5.c:124,673,684,2468-2469,2495`; `verbs.h:3376-3379,1466-1469`. MLNX tarball: same `qp.c`, `cq.c`, `srq.c`, `wqe.h`, `udma_barrier.h`; bracketed lines `mlx5.c:122,671,682,2460-2461,2487`, `verbs.h:3377-3380,1467-1470`, `mlx5dv.h:70-71` all match. nccl@68b5423 `ibvwrap.h:72-73,81-82`; `ibvcore.h:1039-1040`; `net_ib.cc:1055,1736,1772,1809,1892-1898,1492,1951,1983,2021,2064,2102-2124`; no `mlx5` in `src/`. nccl@12df1a1 `gin_host_proxy.cc:21,250-253,113-127,648-669,702-716`; `gin_host.cc:72-79`; `rma.cc:224`; `net_ib/gin.cc:407-409,427-473,501-502,553,689,740,827,796,839-841,867-888,913-914,939,945`; `ibvwrap.h:77-84`; `connect.cc:400-403`. Installed libmlx5: build-id `0a5eddc2` matches; site `0x4eea3-0x4eef4` reads `movzwl 0x2f4`, `bswap`, `mov %eax,0x4(%rsi)`, `sfence`, `mov %rdx,(%rax)`, `sfence`; 10 `sfence` in total | confirmed | Two minor citation issues (discrepancies 1 and 2). Neither changes the reading |
| S2 | UCX CPU rc/dc/ud mlx5 | ucx@8a6b06f `ib_mlx5.inl:580` (`uint16_t sw_pi`), `589-596` (593 `*wq->dbrec = htonl(sw_pi += num_bb)`), `604-623`; `ib_mlx5.c:821`; `dv/ib_mlx5_dv.c:269,201-209`; `dv/ib_mlx5dv_md.c:1707-1725` (pages from `uct_ib_mlx5_md_buf_alloc`: `posix_memalign` plus umem registration, so host memory); `x86_64/cpu.h:40,44`; a grep finds exactly three callers: `rc_mlx5.inl:477,1108`, `ud_mlx5.c:111` | confirmed | |
| S3 | NCCL GIN GDAKI default (GPU rings) | nccl@12df1a1, DOCA copy vendored in NCCL. `qp.cuh`, `cq.cuh`, `counter.cuh` and `verbs_dev.h` are byte-identical to gpunetio@b2b7a29, as the report says. `qp.cuh:524-551` (535 DB, 539 DBR, 546 DB, all under `sq_lock`), `252-272`, `280-286`, `180-186`, `129-144`, `659-662`; `doca_gpunetio.cpp:877` with `uint32_t *dbrec` (778) and `verbs_def.h:249-250`, so word 1; `high_level.cpp:1453-1460`; AUTO resolves to GPU_SM_DB at `doca_gpunetio.cpp:654-678,967-972` and `high_level.cpp:1406-1427`; `gin_gdaki.h:98-111` calls `doca_gpu_dev_verbs_put`, whose `nic_handler` template default is AUTO and which calls `submit`; `gin_host_gdaki.cc:57,58,585,787,792-796` | confirmed | |
| S4 | NCCL GIN GDAKI CPU proxy handler | `doca_gpunetio.cpp:1211-1257` (1239 `htobe32(new_pi & 0xffff)`, 1244-1251 DB, DBR, fence, DB), `1221-1228` (free-flow scan), `935-957`, `1334-1363` (no QP-state check, returns `DOCA_SUCCESS`); `high_level.cpp:710-716` (`calloc` host DBR); `qp.cuh:479-490,638-647,206-216,669-670`; `gin_host_gdaki.cc:1052,1331-1362`; `gin_host.cc:56-87` (the thread exits only on the stop signal or on an error from `ginProgress`) | confirmed | |
| S5 | NCCL GIN GDAKI aggregate-requests hint | `gin_gdaki.h:44-48` (hint becomes SKIP_DB_RINGING); `qp.cuh:505,527` (DB and NO_DBR submits skip); `qp.cuh:638-647` (proxy submit never tests the flag); `gin_gdaki.h:333-334` (`flushAsync` only reads `sq_rsvd_index`), `315-330`, `281`; `gin_host_gdaki.cc:1037`; `docs/examples/09_gin_optimizations/README.md:48-51` | confirmed | One overstated sentence about the MCST WQE (discrepancy 3). The prediction is unaffected |
| S6 | NCCL GIN GDAKI BlueFlame handler (6) | `verbs_def.h:316-320,327-342` (GPU_SM_BF = 2 or 4 = 6); `qp.cuh:659-670`: the AUTO dispatch handles only 2, 10, 1 and 17; the explicit branches at `671-682` have no BF case either; `counter.cuh:216-244`: the multi-QP dispatch has the same gap; `doca_gpunetio.cpp:974` stores handler 6 unchanged; `high_level.cpp:103-136` (BF UAR); `gin_host_gdaki.cc:792` passes the value through, and nothing else in NCCL tests the handler; gpunetio@b2b7a29 `examples/gpunetio_verbs_put_bw/gpunetio_verbs_put_bw_main.cpp:89-92` | confirmed | No doorbell and no DBR write on any device submit path NCCL uses. `submit_bf` (`qp.cuh:565,600`) is never called from NCCL |
| S7 | DOCA no-DBR hardware mode | `doca_verbs_qp.cpp:806` (QPC `send_dbr_mode` from attr), `1404-1408` (`NOT_SUPPORTED` without the cap), `1553-1558` (DBR-less UAR address); `high_level.cpp:807-814` with `doca_verbs.h:329-330` (NO_DBR_EXT = 1), `637-640`; `qp.cuh:502-512` (DB only); `gin_host_gdaki.cc:794-816,843-852` (fallback HW, then SW, then VALID only if the value is 2). ucx@8a6b06f `ib_mlx5.h:653-656`, `dv/ib_mlx5_dv.c:201-209`, `dv/ib_mlx5_ifc.h:1381-1382` (NO_DBR_INT = 2); `sq_no_dbr` is never set in the tree | confirmed | |
| S8 | NVSHMEM 3.4.5 CPU proxy | nvshmem@131da55 `ibgda.cpp:449-462`, `475-476` (`ep->dbr_offset + sizeof(__be32)`), `483-485`, `491-492` (always success), `1790-1794` (host DBR for CPU handlers), `2018`, `2066-2067` (`+= IBGDA_DBRSIZE`, 8), `2421-2424`, `4051-4052`, `4066`; `ibgda_device.cuh:1643-1646`; `proxy.cpp:1122,1139,1148` (loops until stop) | confirmed | |
| S9 | NVSHMEM 3.5.0-3.8.0 CPU proxy, RC and DCI | nvshmem@919760f `ibgda.cpp:533-534`, `541-543` (DCI), `595-596`, `603-605` (RC) `ep->qp_ctrl.dbr_offset * sizeof(__be32)`; `2180` (`calloc` ep), `2188`; `2199` is the only `dbr_offset` setter and is DCI-only; `2206`; `ibgda_host_mem_alloc` memsets to 0. nvshmem@270759e `517-518`, `525-527`, `581-582`, `589-591`, `2369`, `2380`, `2387`, `2139-2143`, `3920`, `5323`. nvshmem@2c7f5a3 `534`, `592` | confirmed | Also checked tags the audit did not read: v3.5.21-0, v3.6.5-0, v3.7.0-0, v3.7.1-0 and v3.7.2-0 all have `* sizeof(__be32)` in both proxy loops, so the 3.5.0-3.8.0 range holds. `ce9d487` is an ancestor of v3.5.19-1 and v3.8.0-0 and not of v3.4.5-0, as the report says |
| S10 | NVSHMEM GPU handler 3.4.5, 3.5.x, 3.8.0 | nvshmem@131da55 `ibgda.cpp:2414-2417`; `ibgda_device.cuh:1570-1592,1594-1601,1619-1624,1682-1694`. nvshmem@919760f `ibgda.cpp:3529-3530`; `ibgda_device.cuh:1579-1601,1613-1636,1691`. nvshmem@270759e `ibgda.cpp:3908-3911`; `ibgda_device.cuh:1527-1549,1551-1558,1577-1582,1671-1689,1702-1717` | confirmed | Every intermediate tag listed under S9 keeps `+ sizeof(__be32)` for the GPU handler |
| S11 | NVSHMEM 3.8.0 batch-RMA region | nvshmem@270759e `ibgda_device.cuh:1671-1688` (`defer_submission`, `do_post_send = batch_limit_reached \|\| (!defer_submission && no_concurrent_submissions)`, mark QP pending), `3646-3670` (pending QPs, then `ibgda_submit_ready`); `transfer_device.cuh.in:334-358` (region end), `444` (quiet), `491` (fence); `host/comm/region.cpp:138-148` (`nvshmemx_region_stop` flush); `env_defs.h:192` (batch 32) | confirmed | |
| S12 | UCX GPU (rc_gda), default delayed posts | ucx@8a6b06f `gdaki.cuh:191-221` (199-200 `skip_db = !(flags & NODELAY) && !((wqe_base ^ wqe_next) & 128)`, 212 `qp_dbrec[MLX5_SND_DBR]`, 216-218 DB, DBR, DB), `269` (the only caller, `count = 1`), `333-336` (empty progress), `349-363`; `gdaki.c:1093-1094` (`iface_flush` returns success and does nothing), `103`, `457`, `463-464`, `471`, `501-504`; `gdaki_dev.h:15`; `ucp_device_impl.h:90-105,403-414` (no device flush call); `test_kernels.cu:139-141`; `uct_device_types.h:52`; `ib_iface.c:104`. gpunetio@f44728f `qp.cuh:186-192` (relaxed system-scope DBR store), `290` (ring_db) | confirmed | |
| S13 | rocSHMEM GDA mlx5 | rocSHMEM@61f20f3 `queue_pair_mlx5.cpp:33-41` (unmasked 32-bit `swap_endian_store`, compiler fence, system seq_cst DB store), `170-182`, `247-259` (leader rings in order), `84-106` (quiet tests only the owner bit and `opcode != INVALID`); `backend_gda_mlx5.cpp:106` (`&qp_out.dbrec[1]`), `118`; `backend_gda.cpp:1220-1225,1231-1248` (`hipHostMalloc` through the parent domain); `endian.cpp:60-64`. A grep of `src/gda` for `REQ_ERR`, `RESP_ERR` and `syndrome` finds only definitions in the vendored `mlx5/mlx5dv.h` and the ionic files; no mlx5 code uses them. rdma-core@bd3282a `dbrec.c:104-106`, `qp.c:769` | confirmed | |
| S14 | DeepEP main | DeepEP@93eb6eb `README.md:18`; `deep_ep/include/deep_ep/comm/handle.cuh:100-170`; `impls/ep/dispatch.cuh:155-156`; `impls/ep/hybrid_dispatch.cuh:179-183,446-451`; `impls/ep/hybrid_combine.cuh:378-383,485-490`; `impls/engram/engram_fetch.cuh:110-112,159-188`. No NVSHMEM or IBGDA code remains, only comments (`hybrid_dispatch.cuh:441,444`, `hybrid_combine.cuh:482`). History: `a56d615` "Ensure that the last get rings the doorbell (#752)" (2026-09-16) is the parent of `def8651` "DeepEP V2.5 (#763)" (2026-09-29), which deletes `csrc/kernels/legacy/` | confirmed | |

Result: 14 of 14 rows confirmed. No commit was wrong and no file was missing.

## Discrepancies

1. **A, NCCL net_ib error path (S1): the cited range stops a few lines early.** The report gives
   `net_ib.cc:2102-2118` for `if (wc->status != IBV_WC_SUCCESS) { ... WARN(...); return ncclRemoteError; }`
   at `68b5423`. The test is at 2108, but the `WARN` is at 2121-2123 and `return ncclRemoteError` is at 2124,
   up to 6 lines past the range. The reading is correct.
2. **A, fork vs upstream note (S1): one differing file is missing from the list.** The note lists the
   provider files that differ between v47.0 and 2307mlnx47. `providers/mlx5/mlx5dv_dr.h` (and the
   `man/` pages) also differ and are not listed. This does not affect the DBR: `qp.c`, `cq.c`, `srq.c`,
   `wqe.h` and `udma_barrier.h` are byte-identical as stated, and the fork's `mlx5dv.h` keeps
   `MLX5_SND_DBR = 1` at line 71.
3. **B N4, MCST WQE (S5): one sentence overstates when the MCST WQE is posted.** The report says that on
   a GPU that needs the MCST dump (pre-Hopper or Data Direct), a flush "also posts an unhinted dump WQE
   that covers" the pending hinted WQEs (`gin_gdaki.h:315-330`). In fact the MCST WQE is posted only when
   a get to that peer is outstanding: `lastIssuedGet > lastVisibleGet` (line 320), and `last_issued_get`
   is set only in the get path (line 281). After puts with only the aggregation hint, a flush posts
   nothing and reads only `sq_rsvd_index` (333-334). This narrows a side remark. The S5 condition ("a later
   unhinted op follows on the QP") is unchanged.

These two items are correct in the report and are recorded for completeness:

- `ce9d487` has author date 2025-10-05 and committer date 2025-10-08, so the report's date is the
  committer date. It is not an ancestor of `2c7f5a3` (main "Version: 3.5.0-0"). That commit carries the
  same `* sizeof(__be32)` change through the squashed main-branch release commit. The report claims
  ancestry only for v3.5.19-1 and against v3.4.5-0, and both claims are correct.
- C reads only v3.5.19-1, `2c7f5a3` and v3.8.0-0, but S9 and S10 cover 3.5.0-3.8.0. The five
  intermediate tags checked here (v3.5.21-0, v3.6.5-0, v3.7.0-0, v3.7.1-0, v3.7.2-0) show the same code,
  so the range is supported.
