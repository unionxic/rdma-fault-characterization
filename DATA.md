# Raw data

Raw data (logs, per-trial records, archives) is not in the git history. It is published as
GitHub Release assets, one `.tar.xz` per result folder. Each archive unpacks to the folder's
repository path, next to the tracked tables (see `docs/GIT_WORKFLOW.md`). Management addresses
read `192.0.2.193/194`, as in the history.

## Result tables

- **Kept in the repository:** the tables a document cites by name, and the data sets behind a
  main table (cited by a run-stamped pattern), plus the write-ups (`.md`) in each result folder.
- **Everything else:** all 667 tables tracked before the pruning are in
  `results-tables-20261006.tar.xz` (same release). They are also at tag
  `archive/results-tables-20261006`.

## Release `data-20261006`

40 raw-data archives (plus the tables archive above), 13714 files, 703.1 MB compressed. Packed by `tools/pack_release.py`.
The three propagation archives were added later the same day with `--whole`.
The full checksums are in the `SHA256SUMS` asset.

```
# fetch one folder's raw data and verify it
gh release download data-20261006 -R unionxic/rdma-fault-characterization -p SHA256SUMS -p '<asset>'
sha256sum -c --ignore-missing SHA256SUMS && tar -xJf '<asset>'
```

| folder | asset | files | MB | sha256 (first 12) | note |
|---|---|--:|--:|---|---|
| `experiments/225-client/02_retry_decomposition/results` | `experiments__225-client__02_retry_decomposition__results.tar.xz` | 1 | 0.00 | `e9d1ba2d24f1` |  |
| `experiments/225-client/08_middleware/results/qa_20260923` | `experiments__225-client__08_middleware__results__qa_20260923.tar.xz` | 3 | 0.00 | `81bab59542ef` |  |
| `harness/ack_timeout/results/20260925` | `harness__ack_timeout__results__20260925.tar.xz` | 470 | 0.09 | `1a7804554161` |  |
| `harness/teardown_order/results/20260925` | `harness__fingerprint_teardown__results__20260925.tar.xz` | 880 | 0.05 | `90607969ed03` | packed before the folder was renamed: unpacks to the old folder name |
| `harness/gpu-initiated/cqe_seq/results` | `harness__gpu-initiated__cqe_seq__results.tar.xz` | 10 | 0.01 | `7f64aac4d552` |  |
| `harness/gpu-initiated/gin/results/20260923` | `harness__gpu-initiated__gin__results__20260923.tar.xz` | 494 | 0.02 | `323d7009d7c4` |  |
| `harness/gpu-initiated/gin_q4/results/20260923` | `harness__gpu-initiated__gin_q4__results__20260923.tar.xz` | 847 | 1.23 | `2cd3fc7802b7` |  |
| `harness/gpu-initiated/gin_q4/results/20260925_n30` | `harness__gpu-initiated__gin_q4__results__20260925_n30.tar.xz` | 17 | 0.32 | `e08090a65341` |  |
| `harness/gpu-initiated/gin_recovery/results/20260924` | `harness__gpu-initiated__gin_recovery__results__20260924.tar.xz` | 786 | 1.43 | `4c9ec3bda517` |  |
| `harness/gpu-initiated/gin_recovery/results/20260924_gpudb` | `harness__gpu-initiated__gin_recovery__results__20260924_gpudb.tar.xz` | 415 | 0.69 | `700ed62e5fce` |  |
| `harness/gpu-initiated/gin_recovery/results/20260925_n30` | `harness__gpu-initiated__gin_recovery__results__20260925_n30.tar.xz` | 3 | 0.33 | `192000362e83` |  |
| `harness/gpu-initiated/gin_recovery/results/20260925_ts1` | `harness__gpu-initiated__gin_recovery__results__20260925_ts1.tar.xz` | 36 | 2.64 | `c581b69fef83` |  |
| `harness/gpu-initiated/gin_recovery/results/20260930_ts2` | `harness__gpu-initiated__gin_recovery__results__20260930_ts2.tar.xz` | 48 | 0.82 | `b4b8c5147989` | unfinished work, branch `wip/gin-s2` |
| `harness/gpu-initiated/gin_recovery/results/20261001_ts2` | `harness__gpu-initiated__gin_recovery__results__20261001_ts2.tar.xz` | 3879 | 0.86 | `f628df6c6b48` | unfinished work, branch `wip/gin-s2` |
| `harness/gpu-initiated/gpu_doorbell/results` | `harness__gpu-initiated__gpu_doorbell__results.tar.xz` | 1 | 0.00 | `76bbc8ee9ee1` |  |
| `harness/gpu-initiated/gpu_doorbell/results/20260924` | `harness__gpu-initiated__gpu_doorbell__results__20260924.tar.xz` | 96 | 0.07 | `7b0b2ff4266e` |  |
| `harness/gpu-initiated/gpu_doorbell/results/20260924_w2` | `harness__gpu-initiated__gpu_doorbell__results__20260924_w2.tar.xz` | 54 | 0.02 | `f2b994f88853` |  |
| `harness/gpu-initiated/nvshmem/results/20260923` | `harness__gpu-initiated__nvshmem__results__20260923.tar.xz` | 193 | 0.08 | `9627f1e7110a` |  |
| `harness/gpu-initiated/nvshmem_ft/results` | `harness__gpu-initiated__nvshmem_ft__results.tar.xz` | 4 | 0.00 | `ef423ad3c9f4` |  |
| `harness/gpu-initiated/nvshmem_ft/results/20260925_n30` | `harness__gpu-initiated__nvshmem_ft__results__20260925_n30.tar.xz` | 8 | 2.08 | `2e3ec3250a48` |  |
| `harness/gpu-initiated/nvshmem_ft/results/20260925_v2` | `harness__gpu-initiated__nvshmem_ft__results__20260925_v2.tar.xz` | 32 | 19.70 | `cca4c8122c34` |  |
| `harness/gpu-initiated/nvshmem_ft/results/20260930_t1` | `harness__gpu-initiated__nvshmem_ft__results__20260930_t1.tar.xz` | 418 | 1.28 | `3cbb0eb83ee8` | unfinished work, branch `wip/nvshmem-t1` |
| `harness/gpu-initiated/nvshmem_ft/results/b1` | `harness__gpu-initiated__nvshmem_ft__results__b1.tar.xz` | 866 | 1.96 | `888d73e92d06` |  |
| `harness/gpu-initiated/nvshmem_ft/results/b2` | `harness__gpu-initiated__nvshmem_ft__results__b2.tar.xz` | 628 | 1.72 | `565602e0b9e6` |  |
| `harness/gpu-initiated/nvshmem_ft/results/smoke` | `harness__gpu-initiated__nvshmem_ft__results__smoke.tar.xz` | 45 | 0.12 | `bd51fcf64e14` |  |
| `harness/gpu-initiated/nvshmem_rootcause/results/20260924` | `harness__gpu-initiated__nvshmem_rootcause__results__20260924.tar.xz` | 177 | 0.05 | `fd446de3fa5f` |  |
| `harness/gpu-initiated/nvshmem_rootcause/results/20260924_abc` | `harness__gpu-initiated__nvshmem_rootcause__results__20260924_abc.tar.xz` | 166 | 0.11 | `4d0765fada6a` |  |
| `harness/gpu-initiated/nvshmem_rootcause/results/20260925_dbrk` | `harness__gpu-initiated__nvshmem_rootcause__results__20260925_dbrk.tar.xz` | 474 | 0.05 | `f10c7a0b42ee` |  |
| `harness/gpu-initiated/nvshmem_rootcause/results/20261001_official380` | `harness__gpu-initiated__nvshmem_rootcause__results__20261001_official380.tar.xz` | 29 | 0.02 | `b80613d4c185` |  |
| `harness/gpu-initiated/propagation/results/20261006_campaign` | `harness__gpu-initiated__propagation__results__20261006_campaign.tar.xz` | 1992 | 578.60 | `9c732944c00f` | added 2026-10-06 18:25; whole folder, repeated files stored as hard links |
| `harness/gpu-initiated/propagation/results/20261006_f4rerun` | `harness__gpu-initiated__propagation__results__20261006_f4rerun.tar.xz` | 145 | 0.02 | `5bbfb1bbaecd` | added 2026-10-06 17:50 |
| `harness/gpu-initiated/propagation/results/20261006_smoke` | `harness__gpu-initiated__propagation__results__20261006_smoke.tar.xz` | 280 | 87.80 | `fa4907aa0564` | added 2026-10-06 17:50; smoke runs, not scored |
| `harness/gpu-initiated/transparent_probe/results/run1` | `harness__gpu-initiated__transparent_probe__results__run1.tar.xz` | 30 | 0.00 | `58aa0ced51b9` |  |
| `harness/gpu-initiated/transparent_probe/results/run2` | `harness__gpu-initiated__transparent_probe__results__run2.tar.xz` | 30 | 0.00 | `0733ed6e3fbc` |  |
| `harness/nccl-integration/logs` | `harness__nccl-integration__logs.tar.xz` | 26 | 0.00 | `d4f8aa492a1f` |  |
| `harness/nccl-integration/perf/results/20260925` | `harness__nccl-integration__perf__results__20260925.tar.xz` | 11 | 0.20 | `d0a51b95a964` |  |
| `harness/nccl-integration/stage2/results/20260925` | `harness__nccl-integration__stage2__results__20260925.tar.xz` | 116 | 0.71 | `27bbf767eb65` |  |
| `harness/results/validation_20260925_no_answer` | `harness__results__validation_20260925_no_answer.tar.xz` | 1 | 0.00 | `b2d7bb57fdad` |  |
| `harness/results/validation_20260925_probe_split` | `harness__results__validation_20260925_probe_split.tar.xz` | 1 | 0.00 | `6de4738a6fa9` |  |
| `harness/results/validation_20260925_remnak` | `harness__results__validation_20260925_remnak.tar.xz` | 2 | 0.00 | `4955ac26fead` |  |

## Release `data-20261007`

12 raw-data archives, 3451 files, 1.74 MB compressed. Packed by `tools/pack_release.py --whole`.
The full checksums are in the `SHA256SUMS` asset of that release.

| folder | asset | files | MB | sha256 (first 12) | note |
|---|---|--:|--:|---|---|
| `harness/gpu-initiated/nvshmem_rootcause/teardown_channel/results/20261007` | `harness__gpu-initiated__nvshmem_rootcause__teardown_channel__results__20261007.tar.xz` | 230 | 0.08 | `4fe553c1c7f4` |  |
| `harness/gpu-initiated/nvshmem_rootcause/teardown_channel/results/20261007_smoke` | `harness__gpu-initiated__nvshmem_rootcause__teardown_channel__results__20261007_smoke.tar.xz` | 12 | 0.01 | `c0f012d0ea9c` | smoke run, not scored |
| `harness/gpu-initiated/nvshmem_rootcause/cq380/results/20261007` | `harness__gpu-initiated__nvshmem_rootcause__cq380__results__20261007.tar.xz` | 115 | 0.06 | `476a79a255d7` |  |
| `harness/gpu-initiated/nvshmem_rootcause/cq380/results/20261007_smoke` | `harness__gpu-initiated__nvshmem_rootcause__cq380__results__20261007_smoke.tar.xz` | 34 | 0.02 | `947c4f180928` | smoke run, not scored |
| `harness/gpu-initiated/completion_contract/results/20261007` | `harness__gpu-initiated__completion_contract__results__20261007.tar.xz` | 226 | 0.08 | `be425b9f5867` |  |
| `harness/gpu-initiated/completion_contract/results/20261007_smoke` | `harness__gpu-initiated__completion_contract__results__20261007_smoke.tar.xz` | 64 | 0.03 | `a1a4f151d8d7` | smoke runs, not scored |
| `harness/gpu-initiated/nvshmem_ft/t1_close/results/20261007` | `harness__gpu-initiated__nvshmem_ft__t1_close__results__20261007.tar.xz` | 666 | 0.40 | `14d8ef769d77` |  |
| `harness/gpu-initiated/nvshmem_ft/t1_close/results/20261007_smoke` | `harness__gpu-initiated__nvshmem_ft__t1_close__results__20261007_smoke.tar.xz` | 78 | 0.12 | `492e253870cd` | smoke runs, not scored |
| `harness/live_peer/results/20261007` | `harness__live_peer__results__20261007.tar.xz` | 743 | 0.13 | `bd2e7b5e19b2` |  |
| `harness/live_peer/results/20261007_smoke` | `harness__live_peer__results__20261007_smoke.tar.xz` | 98 | 0.02 | `f029e949f2cf` | smoke runs, not scored |
| `harness/gpu-initiated/gin_recovery/s2_close/results/20261007` | `harness__gpu-initiated__gin_recovery__s2_close__results__20261007.tar.xz` | 1112 | 0.76 | `f2d11a86cc83` |  |
| `harness/gpu-initiated/gin_recovery/s2_close/results/20261007_smoke` | `harness__gpu-initiated__gin_recovery__s2_close__results__20261007_smoke.tar.xz` | 73 | 0.02 | `12b660398860` | smoke runs, not scored |

## Release `data-20261008`

12 raw-data archives, 4566 files, 1.62 MB compressed. Packed by `tools/pack_release.py --whole`.
The full checksums are in the `SHA256SUMS` asset of that release.

| folder | asset | files | MB | sha256 (first 12) | note |
|---|---|--:|--:|---|---|
| `harness/gpu-initiated/nvshmem_ft/t1_380/results/20261008` | `harness__gpu-initiated__nvshmem_ft__t1_380__results__20261008.tar.xz` | 641 | 0.20 | `cb99b81a5f87` |  |
| `harness/gpu-initiated/nvshmem_ft/t1_380/results/20261008_smoke` | `harness__gpu-initiated__nvshmem_ft__t1_380__results__20261008_smoke.tar.xz` | 58 | 0.09 | `c4a526b28641` | smoke run, not scored |
| `harness/gpu-initiated/gin_recovery/reconnect/results/20261008` | `harness__gpu-initiated__gin_recovery__reconnect__results__20261008.tar.xz` | 653 | 0.26 | `d1dd5ebd0e92` |  |
| `harness/gpu-initiated/gin_recovery/reconnect/results/20261008_smoke` | `harness__gpu-initiated__gin_recovery__reconnect__results__20261008_smoke.tar.xz` | 122 | 0.04 | `8b6cea2e0e01` | smoke runs, not scored |
| `harness/gpu-initiated/gin_recovery/pair_reset/results/20261008` | `harness__gpu-initiated__gin_recovery__pair_reset__results__20261008.tar.xz` | 604 | 0.25 | `f517a5d85a74` |  |
| `harness/gpu-initiated/gin_recovery/pair_reset/results/20261008_smoke` | `harness__gpu-initiated__gin_recovery__pair_reset__results__20261008_smoke.tar.xz` | 69 | 0.03 | `6867007a4dc2` | smoke runs, not scored |
| `harness/live_peer/boundary/results/20261008` | `harness__live_peer__boundary__results__20261008.tar.xz` | 759 | 0.10 | `42d50aa5bf54` |  |
| `harness/live_peer/boundary/results/20261008_smoke` | `harness__live_peer__boundary__results__20261008_smoke.tar.xz` | 120 | 0.02 | `e3d5eaeda26c` | smoke runs, not scored |
| `harness/gpu-initiated/gin_recovery/pair_check/results/20261008` | `harness__gpu-initiated__gin_recovery__pair_check__results__20261008.tar.xz` | 640 | 0.26 | `5c2d76711eb6` |  |
| `harness/gpu-initiated/gin_recovery/pair_check/results/20261008_smoke` | `harness__gpu-initiated__gin_recovery__pair_check__results__20261008_smoke.tar.xz` | 79 | 0.04 | `331423478563` | smoke runs, not scored |
| `harness/gpu-initiated/gin_recovery/oneway/results/20261008` | `harness__gpu-initiated__gin_recovery__oneway__results__20261008.tar.xz` | 729 | 0.28 | `767d75a0265b` |  |
| `harness/gpu-initiated/gin_recovery/oneway/results/20261008_smoke` | `harness__gpu-initiated__gin_recovery__oneway__results__20261008_smoke.tar.xz` | 92 | 0.04 | `5864bf306be6` | smoke runs, not scored |
