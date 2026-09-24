# nrc_devx presets, field by field

`nrc_devx --preset nvshmem|doca` builds the CQ and the RC QP through DEVX with the values
below. Every row with a key can be changed on its own with `--set key=value`.

Sources (all read from the trees the experiments were built from):
- **NV** = NVSHMEM 7bb2e99c `src/modules/transport/ibgda/ibgda.cpp` (clean tree, scratch
  `ibgda/nvshmem`); **NVdev** = `src/include/non_abi/device/pt-to-pt/ibgda_device.cuh`.
- **DQ** = DOCA GPUNetIO bundled in NCCL v2.32.3-1, `src/transport/net_ib/gdaki/doca-gpunetio/src/doca_verbs_qp.cpp`;
  **DC** = `.../doca_verbs_cq.cpp`; **DH** = `.../doca_gpunetio_high_level.cpp`;
  **DG** = `.../doca_gpunetio.cpp`; **Ddev** = `.../include/device/doca_gpunetio_dev_verbs_qp.cuh`;
  **NC** = NCCL `src/transport/net_ib/gdaki/gin_host_gdaki.cc` (what GIN passes to DOCA).
- Defaults assumed: NVSHMEM `QP_DEPTH`=1024 (`common/env_defs.h:121`), `IB_SL`=0, `IB_TRAFFIC_CLASS`=0;
  NCCL `GIN_GDAKI_QP_DEPTH`=128 (NC:58), `GDAKI_USE_RELIABLE_DB`=0 (NC:585, so DBR mode
  "valid"), CPU-proxy NIC handler (no PeerMappingOverride on this cluster).

## CQ (CREATE_CQ)

| field | key | nvshmem | ref | doca | ref |
|---|---|---|---|---|---|
| cqe_sz | - | 64 B | NV:1534 | 64 B | DC:125 |
| cc (collapsed) | `cq_cc` | 1 | NV:1535 | 0 (NCCL stock ring); 1 with collapsed option | DC:126, DH:493 |
| oi (overrun ignore) | `cq_oi` | 1 | NV:1536 | 1 | DC:127, DH:486 |
| log_cq_size | `cq_log_size` | 10 (1024 CQEs) | NV:1490,1538 | 7 (= sq_nwqe 128) | DC:129, DH:1020-1025 |
| log_page_size | `cq_log_page_size` | 4 (64 KiB) | NV:1541 | 0 ("reserved when umem valid") | DC:148 |
| CQ buffer init | `cq_init` | memset 0xff | NV:1447 | op_own=0xf1 per CQE, rest 0 | DH:212-217,452 |
| CQ doorbell record | - | own 8 B buffer, offset 0 | NV:1456,1542 | own page, offset 0 | DC:232,134-136 |
| uar_page | - | NC UAR | NV:1523 | NC UAR | DC:271 |
| c_eqn | - | EQ 0 | NV:1518 | EQ 0 | DC:139-145 |
| consumer index written to CQ DBR | `cq_ci_update` | never | (no writer in NV/NVdev) | not in the GIN path | - |

## QP (CREATE_QP)

| field | key | nvshmem | ref | doca | ref |
|---|---|---|---|---|---|
| st, pm_state | - | RC, MIGRATED | NV:2397-2400 | RC, MIGRATED | DQ:748, 849 |
| log_sq_size | `log_sq_size` | 10 | NV:2407 | 7 (128 x 64 B WQEBB) | DQ:774, DH:763 |
| receive side | `rq_srq` | rq_type SRQ (verbs SRQ) + cqn_rcv (verbs CQ), log_rq_size 0, cs_req/cs_res 0 | NV:2403-2410 | ZERO_SIZE_RQ, no cqn_rcv | DQ:800, DH:769 |
| send_dbr_mode | `send_dbr_mode` | not set (0) | - | 0 (VALID_DBR default) | DQ:806, NC:796 |
| cd_master | `cd_master` | not set (0) | - | 0 (not requested) | DQ:811 |
| user_index | `user_index` | qp index (nrc uses 1) | NV:2417 | 0 | DQ:765 |
| page_offset, log_page_size | - | 0, 0 | NV:2418 | -, 0 | DQ:818 |
| dbr_umem_valid, dbr_addr | - | 1, offset 0 | NV:2411-2416 | 1, offset 0 | DQ:807-809 |
| QP UAR | `uar_type` | NC (NC_DEDICATED absent in rain's headers) | NV:1337-1351, 2356-2357 | NC_DEDICATED attempt, then NC | DH:104-120 |

## RST2INIT / INIT2RTR / RTR2RTS

| field | key | nvshmem | ref | doca (as NCCL calls it) | ref |
|---|---|---|---|---|---|
| RST2INIT rwe, rre | - | 1, 1 | NV:1624-1625 | 1, 1 | DQ:853-861, NC:478-479 |
| RST2INIT rae + atomic_mode | `r2i_rae`, `atomic_mode` | rae 1, mode 3 (UP_TO_64BIT) | NV:1626-1629 | not set (ATOMIC_MODE not in NCCL's mask) | DQ:866-870 |
| vhca_port_num, pkey_index | - | 1, 0 | NV:1632 | 1, 0 | DQ:848,851 |
| counter_set_id | `counter_set_id` | 0 | NV:1651 | 0 | DQ:850 |
| INIT2RTR mtu, log_msg_max, remote_qpn | `log_msg_max` | active, 30, peer | NV:1771-1773 | same, 30 | DQ:973-980 |
| next_rcv_psn | - | not set (0) | - | 0 | DQ:973, NC:522 |
| min_rnr_nak | `min_rnr_nak` | 12 | NV:1774 | 12 | DQ:983, NC:529 |
| log_rra_max | - | log2(max_qp_rd_atom) | NV:1775 | same | DQ:1066 |
| rmac, rgid, hop_limit, src_addr_index | - | from verbs AH, 255 | NV:1906-1915 | resolved MAC, 255 | DQ:992-1020, NC:55 |
| eth_prio | `eth_prio_set` | set to IB_SL = 0 | NV:1911 | not set (0) | - |
| udp_sport | `udp_sport` | 0xC000 (lid 0 OR RoCE v2 base) | NV:1830-1831,1912 | random in [min,max] | DQ:1030-1037 |
| dscp, stat_rate | - | 0, - | NV:1913 | 0, 0 | DQ:990,1038 |
| INIT2RTR rwe, rae, atomic_mode | `rtr_rwe_rae` | not set | - | rwe 1, rae 1, mode 1 (IB_SPEC) | DQ:1044-1063 |
| INIT2RTR opt_param_mask | `rtr_opt_mask` | 0 | - | 0x4 (RAE) | DQ:1080-1082, 370-423 |
| RTR2RTS log_ack_req_freq, log_sra_max | `log_ack_req_freq` | 0, log2(max_qp_rd_atom) | NV:1971-1973 | 0, same | DQ:1133-1135 |
| next_send_psn, retry_count, ack_timeout | (`--retry`, `--timeout`) | 0, IB_RETRY_CNT, IB_TIMEOUT | NV:1974-1977 | 0, IB retry, IB timeout | DQ:1113-1117 |
| rnr_retry | `rnr_retry` | 7 | NV:1976 | 7 | NC:528 |
| RTR2RTS rwe (qpc only, not in opt mask) | `rts_rwe` | not set | - | 1 | DQ:1122-1124 |

## WQEs (put + signal) and doorbell

| item | key | nvshmem | ref | doca | ref |
|---|---|---|---|---|---|
| put | - | RDMA_WRITE, ds 3 | NVdev:3363-3365 | same shape | - |
| put fm_ce_se | `write_ce` | 0 (unsignaled) | NVdev:3365 (fm_ce_se arg 0) | CQ_UPDATE (8) | Ddev:132-144 |
| signal | - | ATOMIC_FA 8 B (SIGNAL_ADD), ds 4 | NVdev:3369-3372 | - | - |
| signal fm_ce_se | `atomic_ce` | CQ_UPDATE (8) | NVdev:3367 | CQ_UPDATE | Ddev:140 |
| doorbell ctrl word | - | opmod_idx_opcode = pi<<8, qpn_ds = qpn<<8 | NV:586-587 | same | DG:1234-1235 |
| **QP doorbell-record word written with pi & 0xffff** | `dbr_word` | **word 0** = `dbr_offset * sizeof(__be32)` with RC dbr_offset 0, i.e. MLX5_RCV_DBR | **NV:581-582, 589** | **word 1** (`dbrec + MLX5_SND_DBR`) | **DG:877, 1245-1247** |
| (GPU handler, for comparison) | - | word 1: `dbr_offset + sizeof(__be32)` | NV:3910-3911, NVdev:1527-1548 | - | - |
| ring order | `db_style` | DBR, release fence, UAR 8 B | NV:589-591 | UAR, DBR, release fence, UAR again | DG:1238-1252 |

nrc_devx keeps every queue in host memory (NVSHMEM: CQ and WQ in GPU memory, QP DBR in
host memory in the CPU-proxy handlers, NV:2139-2143; DOCA: CQ/WQ in GPU memory, DBR in
host memory for the CPU proxy, DH:736-750). Both stacks use one CQ per QP here.
