<!-- 57 trials -> results/20260924/all_trials.csv -->
| tag | fault | preset | sets | error CQE | first error (syn/vendor@wqe, ms) | slot0 | QP final | QP->ERR ms | dbr0/dbr1 | pi | xmit pkts | last xmit change ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| b1_nvs_none | none | nvshmem | - | 0 | - | 0x0/0x08/0xf5@9 | RTS | -1.0 | 10/0 | 10 | 69 | 1100.0 |
| b1_nvs_f2b | f2b | nvshmem | - | 0 | - | 0x0/0xcd/0xbd@7 | ERR | 100.0 | 10/0 | 10 | 75 | 2900.0 |
| b1_doca_f2b | f2b | doca | - | 1 | 0x13/0x88@8, 3.4 | 0x0/0xe6/0x79@0 | ERR | 100.0 | 0/10 | 10 | 75 | 2700.0 |
| b1_nvsdbr1_f2b | f2b | nvshmem | dbr_word=1 | 1 | 0x13/0x88@8, 4.3 | 0xd/0x05/0xf9@9 | ERR | 100.0 | 0/10 | 10 | 73 | 2400.0 |
| b1_nvs_f1 | f1 | nvshmem | - | 0 | - | 0x0/0xaa/0x7d@7 | ERR | 0.3 | 24/0 | 24 | 266 | 2100.0 |
| b1_doca_f1 | f1 | doca | - | 1 | 0x05/0xf5@8, 0.3 | 0x0/0xab/0xfb@0 | ERR | 0.3 | 0/24 | 24 | 273 | 2800.0 |
| b1_nvsdbr1_f1 | f1 | nvshmem | dbr_word=1 | 1 | 0x05/0xf5@8, 0.3 | 0xd/0x05/0xf9@23 | ERR | 0.3 | 0/24 | 24 | 268 | 2700.0 |
| b1_nvs_f1post | f1post | nvshmem | - | 0 | - | 0x0/0x25/0x51@7 | ERR | 0.0 | 10/0 | 10 | 8 | 2300.0 |
| b1_doca_f1post | f1post | doca | - | 1 | 0x05/0xf5@8, 0.4 | 0x0/0xee/0xec@0 | ERR | 0.0 | 0/10 | 10 | 10 | 1900.0 |
| b1_nvsdbr1_f1post | f1post | nvshmem | dbr_word=1 | 1 | 0x05/0xf9@9, 0.4 | 0xd/0x05/0xf9@9 | ERR | 0.0 | 0/10 | 10 | 12 | 2900.0 |
| b1_nvs_f3 | f3 | nvshmem | - | 0 | - | 0x0/0xb1/0x1f@7 | ERR | 3800.0 | 10/0 | 10 | 810 | 9000.0 |
| b1_doca_f3 | f3 | doca | - | 1 | 0x15/0x81@8, 3558.5 | 0x0/0x9a/0xa4@0 | ERR | 3600.0 | 0/10 | 10 | 747 | 9300.0 |
| b1_nvsdbr1_f3 | f3 | nvshmem | dbr_word=1 | 1 | 0x15/0x81@8, 3640.1 | 0xd/0x05/0xf9@9 | ERR | 3700.0 | 0/10 | 10 | 682 | 9600.0 |
| b2_nvs_f2b_r2 | f2b | nvshmem | - | 0 | - | 0x0/0x07/0x0b@7 | ERR | 100.0 | 10/0 | 10 | 75 | 2900.0 |
| b2_nvs_cc0_f2b | f2b | nvshmem | cq_cc=0,cq_log_page_size=0 | 0 | - | 0x0/0x13/0xb0@1 | ERR | 100.0 | 10/0 | 10 | 75 | 2700.0 |
| b2_nvs_cqlog7_f2b | f2b | nvshmem | cq_log_size=7 | 0 | - | 0x0/0x08/0x24@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2400.0 |
| b2_nvs_cqpg0_f2b | f2b | nvshmem | cq_log_page_size=0 | 0 | - | 0x0/0x6d/0x51@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2100.0 |
| b2_nvs_cqinit1_f2b | f2b | nvshmem | cq_init=1 | 0 | - | 0x0/0xd2/0xb9@7 | ERR | 100.0 | 10/0 | 10 | 77 | 2800.0 |
| b2_nvs_sq7_f2b | f2b | nvshmem | log_sq_size=7 | 0 | - | 0x0/0xb2/0x54@7 | ERR | 100.0 | 10/0 | 10 | 75 | 2700.0 |
| b2_nvs_norq_f2b | f2b | nvshmem | rq_srq=0 | 0 | - | 0x0/0x30/0x31@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2300.0 |
| b2_nvs_uidx0_f2b | f2b | nvshmem | user_index=0 | 0 | - | 0x0/0x03/0xa1@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2000.0 |
| b2_nvs_atomicgrp_f2b | f2b | nvshmem | r2i_rae=0,rtr_rwe_rae=1,rtr_opt_mask=4,atomic_mode=1 | 0 | - | 0x0/0x7f/0x37@7 | ERR | 100.0 | 10/0 | 10 | 77 | 2900.0 |
| b2_nvs_sport_f2b | f2b | nvshmem | udp_sport=-1 | 0 | - | 0x0/0xcc/0x8b@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2600.0 |
| b2_nvs_prio_f2b | f2b | nvshmem | eth_prio_set=0 | 0 | - | 0x0/0xaa/0x8b@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2200.0 |
| b2_nvs_rtsrwe_f2b | f2b | nvshmem | rts_rwe=1 | 0 | - | 0x0/0xa1/0xa9@7 | ERR | 100.0 | 10/0 | 10 | 75 | 1900.0 |
| b2_nvs_wce_f2b | f2b | nvshmem | write_ce=8 | 0 | - | 0x0/0x91/0x58@7 | ERR | 100.0 | 10/0 | 10 | 77 | 2800.0 |
| b2_nvs_dbstyle_f2b | f2b | nvshmem | db_style=1 | 0 | - | 0x0/0xf1/0x22@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2500.0 |
| b2_nvs_uarbf_f2b | f2b | nvshmem | uar_type=1 | 0 | - | 0x0/0x4d/0xd6@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2100.0 |
| b2_nvs_dbr1_f2b_r2 | f2b | nvshmem | dbr_word=1 | 1 | 0x13/0x88@8, 4.3 | 0xd/0x05/0xf9@9 | ERR | 100.0 | 0/10 | 10 | 77 | 2800.0 |
| b2_doca_dbr0_f2b | f2b | doca | dbr_word=0 | 0 | - | 0x0/0xd6/0xb3@0 | ERR | 100.0 | 10/0 | 10 | 75 | 2700.0 |
| b2_doca_dbr0style0_f2b | f2b | doca | dbr_word=0,db_style=0 | 0 | - | 0x0/0xce/0x1d@0 | ERR | 100.0 | 10/0 | 10 | 73 | 2300.0 |
| b2_doca_cc1_f2b | f2b | doca | cq_cc=1 | 1 | 0x13/0x88@8, 3.2 | 0xd/0x05/0xf9@9 | ERR | 100.0 | 0/10 | 10 | 73 | 2000.0 |
| b2_doca_cc1dbr0_f2b | f2b | doca | cq_cc=1,dbr_word=0 | 0 | - | 0x0/0x30/0x21@7 | ERR | 100.0 | 10/0 | 10 | 77 | 2900.0 |
| b2_nvs_gpuemu_f2b | f2b | nvshmem | dbr_word=1,uar_type=1 | 1 | 0x13/0x88@8, 4.3 | 0xd/0x05/0xf9@9 | ERR | 100.0 | 0/10 | 10 | 73 | 2600.0 |
| b3_nvs_f3_r2 | f3 | nvshmem | - | 0 | - | 0x0/0xd3/0xea@7 | ERR | 3800.0 | 10/0 | 10 | 747 | 9900.0 |
| b3_nvsdbr1_f3_r2 | f3 | nvshmem | dbr_word=1 | 1 | 0x15/0x81@8, 3534.7 | 0xd/0x05/0xf9@9 | ERR | 3600.0 | 0/10 | 10 | 745 | 9000.0 |
| b3_doca_dbr0_f3 | f3 | doca | dbr_word=0 | 0 | - | 0x0/0x9b/0x98@0 | ERR | 3700.0 | 10/0 | 10 | 747 | 9300.0 |
| b3_nvs_f3_qc | f3 | nvshmem | - | 0 | - | 0x0/0xb0/0xc6@7 | ERR | 3700.0 | 10/0 | 10 | 812 | 9600.0 |
| b3_nvsdbr1_f3_qc | f3 | nvshmem | dbr_word=1 | 1 | 0x15/0x81@8, 3516.5 | 0xd/0x05/0xf9@9 | ERR | 3600.0 | 0/10 | 10 | 747 | 9900.0 |
| b3_nvs_f2b_qc | f2b | nvshmem | - | 0 | - | 0x0/0xf7/0x61@7 | ERR | 100.0 | 10/0 | 10 | 73 | 2600.0 |
| b3_nvsdbr1_f2b_qc | f2b | nvshmem | dbr_word=1 | 1 | 0x13/0x88@8, 4.3 | 0xd/0x05/0xf9@9 | ERR | 100.0 | 0/10 | 10 | 73 | 2200.0 |
| b3_nvs_f1_r2 | f1 | nvshmem | - | 0 | - | 0x0/0x2c/0xad@7 | ERR | 0.3 | 24/0 | 24 | 266 | 1900.0 |
| b3_nvsdbr1_f1_r2 | f1 | nvshmem | dbr_word=1 | 1 | 0x05/0xf5@8, 0.3 | 0xd/0x05/0xf9@23 | ERR | 0.3 | 0/24 | 24 | 274 | 2800.0 |
| b3_nvs_f1post_r2 | f1post | nvshmem | - | 0 | - | 0x0/0x6a/0x15@7 | ERR | 0.0 | 10/0 | 10 | 8 | 2400.0 |
| b3_nvsdbr1_f1post_r2 | f1post | nvshmem | dbr_word=1 | 1 | 0x05/0xf5@8, 0.0 | 0xd/0x05/0xf9@9 | ERR | 0.0 | 0/10 | 10 | 8 | 2100.0 |
| b3_nvs_f3_r3 | f3 | nvshmem | - | 0 | - | 0x0/0xd6/0x3c@7 | ERR | 3700.0 | 10/0 | 10 | 682 | 9400.0 |
| b3_nvsdbr1_f3_r3 | f3 | nvshmem | dbr_word=1 | 1 | 0x15/0x81@8, 3766.7 | 0xd/0x05/0xf9@9 | ERR | 3800.0 | 0/10 | 10 | 747 | 9800.0 |
| b4_doca_f2b_r2 | f2b | doca | - | 1 | 0x13/0x88@8, 6.2 | 0x0/0x8b/0x24@0 | ERR | 100.0 | 0/10 | 10 | 77 | 2800.0 |
| b4_doca_dbr0_f2b_r2 | f2b | doca | dbr_word=0 | 0 | - | 0x0/0x3c/0x12@0 | ERR | 100.0 | 10/0 | 10 | 75 | 2700.0 |
| b4_doca_f1_r2 | f1 | doca | - | 1 | 0x05/0xf5@8, 0.4 | 0x0/0x35/0x4a@0 | ERR | 0.4 | 0/24 | 24 | 561 | 2400.0 |
| b4_doca_dbr0_f1 | f1 | doca | dbr_word=0 | 0 | - | 0x0/0x73/0xe5@0 | ERR | 0.3 | 24/0 | 24 | 264 | 2100.0 |
| b4_doca_dbr0_f1_r2 | f1 | doca | dbr_word=0 | 0 | - | 0x0/0xde/0x4a@0 | ERR | 0.3 | 24/0 | 24 | 273 | 2800.0 |
| b4_doca_f1post_r2 | f1post | doca | - | 1 | 0x05/0xf5@8, 0.4 | 0x0/0xd7/0x58@0 | ERR | 0.0 | 0/10 | 10 | 10 | 2600.0 |
| b4_doca_dbr0_f1post | f1post | doca | dbr_word=0 | 0 | - | 0x0/0xfd/0x1d@0 | ERR | 0.0 | 10/0 | 10 | 8 | 2300.0 |
| b4_doca_dbr0_f1post_r2 | f1post | doca | dbr_word=0 | 0 | - | 0x0/0x3a/0x35@0 | ERR | 0.0 | 10/0 | 10 | 10 | 1900.0 |
| b4_doca_f3_r2 | f3 | doca | - | 1 | 0x15/0x81@8, 3602.2 | 0x0/0x79/0xbb@0 | ERR | 3700.0 | 0/10 | 10 | 877 | 9300.0 |
| b4_doca_dbr0_f3_r2 | f3 | doca | dbr_word=0 | 0 | - | 0x0/0x27/0x39@0 | ERR | 3700.0 | 10/0 | 10 | 682 | 9600.0 |
<!-- 18 NVSHMEM trials -> results/20260924/nvshmem_trials.csv -->
