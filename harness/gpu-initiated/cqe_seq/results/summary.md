| fault | N | sig | k | first CQE | root cause | last CQE (collapsed slot) | #CQE | #flush | unsig. flush | succ<root | last=root | t0->root us | root->next us | root->last us | QP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| local_qp_err (4096 B) | 1 | all | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@0 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 1 | last | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@0 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 4 | all | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@3 | 4 | 0 | n/a | 4 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 4 | last | none | SUCCESS/0x0@3 | none | SUCCESS/0x0@3 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 16 | all | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@15 | 16 | 0 | n/a | 16 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 16 | last | none | SUCCESS/0x0@15 | none | SUCCESS/0x0@15 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 64 | all | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@63 | 64 | 0 | n/a | 64 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (4096 B) | 64 | last | none | SUCCESS/0x0@63 | none | SUCCESS/0x0@63 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (65536 B) | 1 | all | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@0 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (65536 B) | 1 | last | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@0 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (65536 B) | 4 | all | none | SUCCESS/0x0@0 | none | SUCCESS/0x0@3 | 4 | 0 | n/a | 4 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (65536 B) | 4 | last | none | SUCCESS/0x0@3 | none | SUCCESS/0x0@3 | 1 | 0 | n/a | 1 | - | - | - (max -) | - (max -) | ERR |
| local_qp_err (65536 B) | 16 | all | none | SUCCESS/0x0@0 | WR_FLUSH/0xf5@14 | WR_FLUSH/0xf9@15 | 16 | 2 | n/a | 14 | 0/5 | 224.5 | 63.79 (max 223.10) | 63.79 (max 223.10) | ERR |
| local_qp_err (65536 B) | 16 | last | none | WR_FLUSH/0xf5@14 (4/5); WR_FLUSH/0xf5@13 (1/5) | WR_FLUSH/0xf5@14 (4/5); WR_FLUSH/0xf5@13 (1/5) | WR_FLUSH/0xf9@15 | 2-3 | 2-3 | yes (1-2 of 1-2) | 0 | 0/5 | 223.8 | 61.27 (max 61.93) | 61.87 (max 69.37) | ERR |
| local_qp_err (65536 B) | 64 | all | none | SUCCESS/0x0@0 | WR_FLUSH/0xf5@13 (3/5); WR_FLUSH/0xf5@14 (2/5) | WR_FLUSH/0xf9@63 | 64 | 50-51 | n/a | 13-14 | 0/5 | 223.9 | 60.77 (max 62.04) | 518.08 (max 519.13) | ERR |
| local_qp_err (65536 B) | 64 | last | none | WR_FLUSH/0xf5@13 (3/5); WR_FLUSH/0xf5@14 (2/5) | WR_FLUSH/0xf5@13 (3/5); WR_FLUSH/0xf5@14 (2/5) | WR_FLUSH/0xf9@63 | 50-51 | 50-51 | yes (49-50 of 49-50) | 0 | 0/5 | 224.2 | 60.59 (max 61.46) | 516.76 (max 518.65) | ERR |
| local_qp_err (4194304 B) | 1 | all | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | 1 | 1 | n/a | 0 | 5/5 | 225.0 | - (max -) | 0.00 (max 0.00) | ERR |
| local_qp_err (4194304 B) | 1 | last | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | 1 | 1 | n/a | 0 | 5/5 | 223.0 | - (max -) | 0.00 (max 0.00) | ERR |
| local_qp_err (4194304 B) | 4 | all | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf9@3 | 4 | 4 | n/a | 0 | 0/5 | 223.1 | 59.30 (max 59.46) | 78.07 (max 78.16) | ERR |
| local_qp_err (4194304 B) | 4 | last | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf9@3 | 4 | 4 | yes (3 of 3) | 0 | 0/5 | 225.4 | 60.61 (max 60.98) | 79.49 (max 80.05) | ERR |
| local_qp_err (4194304 B) | 16 | all | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf9@15 | 16 | 16 | n/a | 0 | 0/5 | 222.4 | 60.89 (max 60.97) | 191.46 (max 191.73) | ERR |
| local_qp_err (4194304 B) | 16 | last | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf9@15 | 16 | 16 | yes (15 of 15) | 0 | 0/5 | 223.0 | 59.35 (max 59.63) | 190.03 (max 190.78) | ERR |
| local_qp_err (4194304 B) | 64 | all | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf9@63 | 64 | 64 | n/a | 0 | 0/5 | 226.3 | 59.90 (max 62.12) | 644.63 (max 651.01) | ERR |
| local_qp_err (4194304 B) | 64 | last | none | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf5@0 | WR_FLUSH/0xf9@63 | 64 | 64 | yes (63 of 63) | 0 | 0/5 | 222.5 | 59.41 (max 60.91) | 638.52 (max 642.03) | ERR |
| rem_access | 1 | all | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | 1 | 0 | n/a | 0 | 5/5 | 2943.5 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 1 | last | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | 1 | 0 | n/a | 0 | 5/5 | 2948.1 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 4 | all | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | WR_FLUSH/0xf9@3 | 4 | 3 | n/a | 0 | 0/5 | 2975.6 | 59.70 (max 60.36) | 78.56 (max 79.52) | ERR |
| rem_access | 4 | all | middle(2) | SUCCESS/0x0@0 | REM_ACCESS/0x88@2 | WR_FLUSH/0xf9@3 | 4 | 1 | n/a | 2 | 0/5 | 2956.0 | 59.34 (max 60.18) | 59.34 (max 60.18) | ERR |
| rem_access | 4 | all | last(3) | SUCCESS/0x0@0 | REM_ACCESS/0x88@3 | REM_ACCESS/0x88@3 | 4 | 0 | n/a | 3 | 5/5 | 2974.2 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 4 | last | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | WR_FLUSH/0xf9@3 | 4 | 3 | yes (2 of 2) | 0 | 0/5 | 2972.6 | 59.51 (max 59.85) | 78.79 (max 78.92) | ERR |
| rem_access | 4 | last | middle(2) | REM_ACCESS/0x88@2 | REM_ACCESS/0x88@2 | WR_FLUSH/0xf9@3 | 2 | 1 | n/a | 0 | 0/5 | 2958.6 | 59.21 (max 59.66) | 59.21 (max 59.66) | ERR |
| rem_access | 4 | last | last(3) | REM_ACCESS/0x88@3 | REM_ACCESS/0x88@3 | REM_ACCESS/0x88@3 | 1 | 0 | n/a | 0 | 5/5 | 2953.0 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 16 | all | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | WR_FLUSH/0xf9@15 | 16 | 15 | n/a | 0 | 0/5 | 3036.6 | 59.14 (max 59.44) | 190.52 (max 190.81) | ERR |
| rem_access | 16 | all | middle(8) | SUCCESS/0x0@0 | REM_ACCESS/0x88@8 | WR_FLUSH/0xf9@15 | 16 | 7 | n/a | 8 | 0/5 | 3004.3 | 59.97 (max 60.54) | 116.38 (max 117.73) | ERR |
| rem_access | 16 | all | last(15) | SUCCESS/0x0@0 | REM_ACCESS/0x88@15 | REM_ACCESS/0x88@15 | 16 | 0 | n/a | 15 | 5/5 | 2961.1 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 16 | last | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | WR_FLUSH/0xf9@15 | 16 | 15 | yes (14 of 14) | 0 | 0/5 | 3036.2 | 59.27 (max 59.40) | 190.20 (max 190.41) | ERR |
| rem_access | 16 | last | middle(8) | REM_ACCESS/0x88@8 | REM_ACCESS/0x88@8 | WR_FLUSH/0xf9@15 | 8 | 7 | yes (6 of 6) | 0 | 0/5 | 3003.8 | 59.32 (max 61.29) | 115.92 (max 121.84) | ERR |
| rem_access | 16 | last | last(15) | REM_ACCESS/0x88@15 | REM_ACCESS/0x88@15 | REM_ACCESS/0x88@15 | 1 | 0 | n/a | 0 | 5/5 | 2963.8 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 64 | all | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | WR_FLUSH/0xf9@63 | 64 | 63 | n/a | 0 | 0/5 | 1777.3 | 59.29 (max 60.30) | 638.97 (max 645.14) | ERR |
| rem_access | 64 | all | middle(32) | SUCCESS/0x0@0 | REM_ACCESS/0x88@32 | WR_FLUSH/0xf9@63 | 64 | 31 | n/a | 32 | 0/5 | 1778.4 | 58.97 (max 59.34) | 339.34 (max 339.58) | ERR |
| rem_access | 64 | all | last(63) | SUCCESS/0x0@0 | REM_ACCESS/0x88@63 | REM_ACCESS/0x88@63 | 64 | 0 | n/a | 63 | 5/5 | 2977.4 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_access | 64 | last | first(0) | REM_ACCESS/0x88@0 | REM_ACCESS/0x88@0 | WR_FLUSH/0xf9@63 | 64 | 63 | yes (62 of 62) | 0 | 0/5 | 1773.1 | 59.28 (max 59.56) | 639.03 (max 642.34) | ERR |
| rem_access | 64 | last | middle(32) | REM_ACCESS/0x88@32 | REM_ACCESS/0x88@32 | WR_FLUSH/0xf9@63 | 32 | 31 | yes (30 of 30) | 0 | 0/5 | 1782.1 | 59.81 (max 60.18) | 340.02 (max 343.74) | ERR |
| rem_access | 64 | last | last(63) | REM_ACCESS/0x88@63 | REM_ACCESS/0x88@63 | REM_ACCESS/0x88@63 | 1 | 0 | n/a | 0 | 5/5 | 2986.3 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 1 | all | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | 1 | 0 | n/a | 0 | 5/5 | 1631.6 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 1 | last | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | 1 | 0 | n/a | 0 | 5/5 | 1616.2 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 4 | all | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | WR_FLUSH/0xf9@3 | 4 | 3 | n/a | 0 | 0/5 | 1613.5 | 59.39 (max 59.74) | 78.43 (max 78.73) | ERR |
| rem_inv_req | 4 | all | middle(2) | SUCCESS/0x0@0 | REM_INV_REQ/0x8a@2 | WR_FLUSH/0xf9@3 | 4 | 1 | n/a | 2 | 0/5 | 1618.4 | 59.78 (max 60.51) | 59.78 (max 60.51) | ERR |
| rem_inv_req | 4 | all | last(3) | SUCCESS/0x0@0 | REM_INV_REQ/0x8a@3 | REM_INV_REQ/0x8a@3 | 4 | 0 | n/a | 3 | 5/5 | 1622.4 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 4 | last | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | WR_FLUSH/0xf9@3 | 4 | 3 | yes (2 of 2) | 0 | 0/5 | 1614.3 | 59.33 (max 59.54) | 78.25 (max 78.69) | ERR |
| rem_inv_req | 4 | last | middle(2) | REM_INV_REQ/0x8a@2 | REM_INV_REQ/0x8a@2 | WR_FLUSH/0xf9@3 | 2 | 1 | n/a | 0 | 0/5 | 1621.6 | 59.83 (max 60.08) | 59.83 (max 60.08) | ERR |
| rem_inv_req | 4 | last | last(3) | REM_INV_REQ/0x8a@3 | REM_INV_REQ/0x8a@3 | REM_INV_REQ/0x8a@3 | 1 | 0 | n/a | 0 | 5/5 | 1616.4 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 16 | all | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | WR_FLUSH/0xf9@15 | 16 | 15 | n/a | 0 | 0/5 | 358.9 | 59.32 (max 59.56) | 190.41 (max 190.80) | ERR |
| rem_inv_req | 16 | all | middle(8) | SUCCESS/0x0@0 | REM_INV_REQ/0x8a@8 | WR_FLUSH/0xf9@15 | 16 | 7 | n/a | 8 | 0/5 | 363.9 | 59.06 (max 59.53) | 115.71 (max 115.98) | ERR |
| rem_inv_req | 16 | all | last(15) | SUCCESS/0x0@0 | REM_INV_REQ/0x8a@15 | REM_INV_REQ/0x8a@15 | 16 | 0 | n/a | 15 | 5/5 | 1624.2 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 16 | last | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | WR_FLUSH/0xf9@15 | 16 | 15 | yes (14 of 14) | 0 | 0/5 | 363.3 | 59.47 (max 60.02) | 190.73 (max 192.87) | ERR |
| rem_inv_req | 16 | last | middle(8) | REM_INV_REQ/0x8a@8 | REM_INV_REQ/0x8a@8 | WR_FLUSH/0xf9@15 | 8 | 7 | yes (6 of 6) | 0 | 0/5 | 364.7 | 59.43 (max 59.45) | 115.85 (max 115.87) | ERR |
| rem_inv_req | 16 | last | last(15) | REM_INV_REQ/0x8a@15 | REM_INV_REQ/0x8a@15 | REM_INV_REQ/0x8a@15 | 1 | 0 | n/a | 0 | 5/5 | 1621.4 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 64 | all | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | WR_FLUSH/0xf9@63 | 64 | 63 | n/a | 0 | 0/5 | 359.8 | 59.41 (max 59.73) | 638.66 (max 641.18) | ERR |
| rem_inv_req | 64 | all | middle(32) | SUCCESS/0x0@0 | REM_INV_REQ/0x8a@32 | WR_FLUSH/0xf9@63 | 64 | 31 | n/a | 32 | 0/5 | 375.6 | 59.10 (max 60.37) | 342.04 (max 344.05) | ERR |
| rem_inv_req | 64 | all | last(63) | SUCCESS/0x0@0 | REM_INV_REQ/0x8a@63 | REM_INV_REQ/0x8a@63 | 64 | 0 | n/a | 63 | 5/5 | 1638.4 | - (max -) | 0.00 (max 0.00) | ERR |
| rem_inv_req | 64 | last | first(0) | REM_INV_REQ/0x8a@0 | REM_INV_REQ/0x8a@0 | WR_FLUSH/0xf9@63 | 64 | 63 | yes (62 of 62) | 0 | 0/5 | 359.8 | 59.26 (max 59.59) | 638.25 (max 638.67) | ERR |
| rem_inv_req | 64 | last | middle(32) | REM_INV_REQ/0x8a@32 | REM_INV_REQ/0x8a@32 | WR_FLUSH/0xf9@63 | 32 | 31 | yes (30 of 30) | 0 | 0/5 | 373.9 | 59.36 (max 59.59) | 339.64 (max 340.19) | ERR |
| rem_inv_req | 64 | last | last(63) | REM_INV_REQ/0x8a@63 | REM_INV_REQ/0x8a@63 | REM_INV_REQ/0x8a@63 | 1 | 0 | n/a | 0 | 5/5 | 1638.3 | - (max -) | 0.00 (max 0.00) | ERR |
| rnr | 1 | all | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | 1 | 0 | n/a | 0 | 5/5 | 12662.2 | - (max -) | 0.00 (max 0.00) | ERR |
| rnr | 1 | last | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | 1 | 0 | n/a | 0 | 5/5 | 12651.8 | - (max -) | 0.00 (max 0.00) | ERR |
| rnr | 4 | all | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | WR_FLUSH/0xf9@3 | 4 | 3 | n/a | 0 | 0/5 | 12597.2 | 58.77 (max 59.52) | 77.72 (max 78.51) | ERR |
| rnr | 4 | all | middle(2) | SUCCESS/0x0@0 | RNR_RETRY_EXC/0x87@2 | WR_FLUSH/0xf9@3 | 4 | 1 | n/a | 2 | 0/5 | 12582.4 | 58.96 (max 60.11) | 58.96 (max 60.11) | ERR |
| rnr | 4 | last | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | WR_FLUSH/0xf9@3 | 4 | 3 | yes (2 of 2) | 0 | 0/5 | 12574.8 | 59.00 (max 60.48) | 77.97 (max 79.16) | ERR |
| rnr | 4 | last | middle(2) | RNR_RETRY_EXC/0x87@2 | RNR_RETRY_EXC/0x87@2 | WR_FLUSH/0xf9@3 | 2 | 1 | n/a | 0 | 0/5 | 12596.8 | 58.98 (max 59.21) | 58.98 (max 59.21) | ERR |
| rnr | 16 | all | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | WR_FLUSH/0xf9@15 | 16 | 15 | n/a | 0 | 0/5 | 12430.4 | 59.19 (max 65.48) | 190.37 (max 197.99) | ERR |
| rnr | 16 | all | middle(8) | SUCCESS/0x0@0 | RNR_RETRY_EXC/0x87@8 | WR_FLUSH/0xf9@15 | 16 | 7 | n/a | 8 | 0/5 | 12505.9 | 58.85 (max 59.42) | 115.44 (max 115.80) | ERR |
| rnr | 16 | last | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | WR_FLUSH/0xf9@15 | 16 | 15 | yes (14 of 14) | 0 | 0/5 | 12446.5 | 58.93 (max 59.37) | 190.13 (max 192.69) | ERR |
| rnr | 16 | last | middle(8) | RNR_RETRY_EXC/0x87@8 | RNR_RETRY_EXC/0x87@8 | WR_FLUSH/0xf9@15 | 8 | 7 | yes (6 of 6) | 0 | 0/5 | 12522.2 | 58.97 (max 60.27) | 115.69 (max 117.45) | ERR |
| rnr | 64 | all | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | WR_FLUSH/0xf9@63 | 64 | 63 | n/a | 0 | 0/5 | 12977.4 | 59.04 (max 59.33) | 638.49 (max 638.65) | ERR |
| rnr | 64 | all | middle(32) | SUCCESS/0x0@0 | RNR_RETRY_EXC/0x87@32 | WR_FLUSH/0xf9@63 | 64 | 31 | n/a | 32 | 0/5 | 12236.5 | 58.99 (max 59.97) | 339.35 (max 343.39) | ERR |
| rnr | 64 | last | first(0) | RNR_RETRY_EXC/0x87@0 | RNR_RETRY_EXC/0x87@0 | WR_FLUSH/0xf9@63 | 64 | 63 | yes (62 of 62) | 0 | 0/5 | 12977.9 | 58.94 (max 59.99) | 638.00 (max 645.26) | ERR |
| rnr | 64 | last | middle(32) | RNR_RETRY_EXC/0x87@32 | RNR_RETRY_EXC/0x87@32 | WR_FLUSH/0xf9@63 | 32 | 31 | yes (30 of 30) | 0 | 0/5 | 12270.8 | 58.77 (max 59.20) | 339.46 (max 340.36) | ERR |
| retry_server_qp_err | 1 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | 1 | 0 | n/a | 0 | 5/5 | 3525217.2 | - (max -) | 0.00 (max 0.00) | ERR |
| retry_server_qp_err | 1 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | 1 | 0 | n/a | 0 | 5/5 | 3525183.6 | - (max -) | 0.00 (max 0.00) | ERR |
| retry_server_qp_err | 4 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@3 | 4 | 3 | n/a | 0 | 0/5 | 3525135.0 | 61.18 (max 61.22) | 80.19 (max 81.02) | ERR |
| retry_server_qp_err | 4 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@3 | 4 | 3 | yes (2 of 2) | 0 | 0/5 | 3525115.3 | 61.02 (max 61.83) | 80.21 (max 81.18) | ERR |
| retry_server_qp_err | 16 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@15 | 16 | 15 | n/a | 0 | 0/5 | 3525019.2 | 60.45 (max 61.46) | 192.35 (max 193.42) | ERR |
| retry_server_qp_err | 16 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@15 | 16 | 15 | yes (14 of 14) | 0 | 0/5 | 3524984.8 | 60.99 (max 61.43) | 193.06 (max 194.25) | ERR |
| retry_server_qp_err | 64 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@63 | 64 | 63 | n/a | 0 | 0/5 | 3524465.0 | 60.47 (max 61.45) | 642.73 (max 650.20) | ERR |
| retry_server_qp_err | 64 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@63 | 64 | 63 | yes (62 of 62) | 0 | 0/5 | 3524441.2 | 60.67 (max 62.02) | 643.14 (max 651.57) | ERR |
| retry_proc_kill | 1 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | 1 | 0 | n/a | 0 | 5/5 | 3578723.1 | - (max -) | 0.00 (max 0.00) | ERR |
| retry_proc_kill | 1 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | 1 | 0 | n/a | 0 | 5/5 | 3567866.8 | - (max -) | 0.00 (max 0.00) | ERR |
| retry_proc_kill | 4 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@3 | 4 | 3 | n/a | 0 | 0/5 | 3570199.4 | 60.24 (max 61.51) | 79.42 (max 81.24) | ERR |
| retry_proc_kill | 4 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@3 | 4 | 3 | yes (2 of 2) | 0 | 0/5 | 3576449.5 | 59.97 (max 61.55) | 79.13 (max 80.90) | ERR |
| retry_proc_kill | 16 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@15 | 16 | 15 | n/a | 0 | 0/5 | 3569569.3 | 60.28 (max 64.06) | 192.24 (max 195.76) | ERR |
| retry_proc_kill | 16 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@15 | 16 | 15 | yes (14 of 14) | 0 | 0/5 | 3575479.2 | 60.65 (max 61.28) | 192.59 (max 194.30) | ERR |
| retry_proc_kill | 64 | all | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@63 | 64 | 63 | n/a | 0 | 0/5 | 3566380.9 | 60.49 (max 60.86) | 642.66 (max 643.12) | ERR |
| retry_proc_kill | 64 | last | none | RETRY_EXC/0x81@0 | RETRY_EXC/0x81@0 | WR_FLUSH/0xf9@63 | 64 | 63 | yes (62 of 62) | 0 | 0/5 | 3570326.0 | 60.43 (max 60.97) | 643.18 (max 649.67) | ERR |
